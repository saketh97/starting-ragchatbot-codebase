import anthropic
from typing import List, Optional, Dict, Any


class AIGenerator:
    """Handles interactions with Anthropic's Claude API for generating responses"""

    # Static system prompt to avoid rebuilding on each call
    SYSTEM_PROMPT = """ You are an AI assistant specialized in course materials and educational content with access to tools for course information.

Available Tools:
- `search_course_content`: for questions about specific course content or detailed educational materials
- `get_course_outline`: for outline-related queries (e.g. "what's the outline of...", "what lessons does ... have", "list the lessons in ...")

Outline Tool Usage:
- For outline-related queries, use `get_course_outline`, not the content search
- Always return the course title, the course link, and the complete lesson list, giving the number and the title of each lesson

Search Tool Usage:
- Use the search tool **only** for questions about specific course content or detailed educational materials
- **One search per query maximum**
- Synthesize search results into accurate, fact-based responses
- If search yields no results, state this clearly without offering alternatives

Response Protocol:
- **General knowledge questions**: Answer using existing knowledge without searching
- **Course-specific questions**: Search first, then answer
- **No meta-commentary**:
 - Provide direct answers only — no reasoning process, search explanations, or question-type analysis
 - Do not mention "based on the search results"


All responses must be:
1. **Brief, Concise and focused** - Get to the point quickly
2. **Educational** - Maintain instructional value
3. **Clear** - Use accessible language
4. **Example-supported** - Include relevant examples when they aid understanding
Provide only the direct answer to what was asked.
"""

    MAX_TOOL_ROUNDS = 2

    def __init__(self, api_key: str, model: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

        # Pre-build base API parameters
        self.base_params = {"model": self.model, "max_tokens": 4000}

    def generate_response(
        self,
        query: str,
        conversation_history: Optional[str] = None,
        tools: Optional[List] = None,
        tool_manager=None,
    ) -> str:
        """
        Generate AI response with optional tool usage and conversation context.

        Args:
            query: The user's question or request
            conversation_history: Previous messages for context
            tools: Available tools the AI can use
            tool_manager: Manager to execute tools

        Returns:
            Generated response as string
        """

        # Build system content efficiently - avoid string ops when possible
        system_content = (
            f"{self.SYSTEM_PROMPT}\n\nPrevious conversation:\n{conversation_history}"
            if conversation_history
            else self.SYSTEM_PROMPT
        )

        # Prepare API call parameters efficiently
        api_params = {
            **self.base_params,
            "messages": [{"role": "user", "content": query}],
            "system": system_content,
        }

        # Add tools if available
        if tools:
            api_params["tools"] = tools
            api_params["tool_choice"] = {"type": "auto"}

        # Get response from Claude
        response = self.client.messages.create(**api_params)

        # Handle tool execution if needed
        if response.stop_reason == "tool_use" and tool_manager:
            return self._handle_tool_execution(response, api_params, tool_manager)

        # Return direct response
        return self._extract_text(response)

    EMPTY_ANSWER = (
        "I couldn't generate an answer to that. Please try rephrasing your question."
    )

    @classmethod
    def _extract_text(cls, response) -> str:
        """Join the text blocks of a response, skipping thinking/tool_use blocks.
        Never returns an empty string (e.g. no text blocks, or tool_use with no tool manager).
        """
        text = "".join(block.text for block in response.content if block.type == "text")
        return text if text.strip() else cls.EMPTY_ANSWER

    def _handle_tool_execution(
        self, initial_response, base_params: Dict[str, Any], tool_manager
    ):
        """
        Execute tool calls and get the follow-up response.

        The model may search again after seeing results (e.g. broad questions),
        so tools stay enabled for follow-up calls until the last round, which
        runs without tools to force a text answer.

        Args:
            initial_response: The response containing tool use requests
            base_params: Base API parameters
            tool_manager: Manager to execute tools

        Returns:
            Final response text after tool execution
        """
        messages = base_params["messages"].copy()
        response = initial_response

        for round_num in range(self.MAX_TOOL_ROUNDS):
            # Add AI's tool use response
            messages.append({"role": "assistant", "content": response.content})

            # Execute all tool calls and collect results
            tool_results = []
            for content_block in response.content:
                if content_block.type == "tool_use":
                    result_block = {
                        "type": "tool_result",
                        "tool_use_id": content_block.id,
                    }
                    try:
                        result_block["content"] = tool_manager.execute_tool(
                            content_block.name, **content_block.input
                        )
                    except Exception as e:
                        # Let the model see the failure instead of failing the whole request
                        result_block["content"] = (
                            f"Tool '{content_block.name}' failed: {e}"
                        )
                        result_block["is_error"] = True

                    tool_results.append(result_block)

            # On the last round tools are dropped; tell the model to answer now,
            # otherwise it can end its turn with an empty response
            last_round = round_num == self.MAX_TOOL_ROUNDS - 1
            if last_round:
                tool_results.append(
                    {
                        "type": "text",
                        "text": "Now answer the original question using the search results above.",
                    }
                )

            # Add tool results as single message
            messages.append({"role": "user", "content": tool_results})

            # Follow-up call; drop tools on the last round to force an answer
            params = {
                **self.base_params,
                "messages": messages,
                "system": base_params["system"],
            }
            if not last_round and "tools" in base_params:
                params["tools"] = base_params["tools"]
                params["tool_choice"] = {"type": "auto"}

            response = self.client.messages.create(**params)
            if response.stop_reason != "tool_use":
                break

        return self._extract_text(response)
