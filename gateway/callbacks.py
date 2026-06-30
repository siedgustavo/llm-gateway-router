import json
import os
from litellm.integrations.custom_logger import CustomLogger

MAX_OUTPUT_TOKENS = 14336
DEBUG_LOG = "/tmp/qwen_request_debug.json"


class MaxTokensCapper(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if data.get("max_tokens", 0) > MAX_OUTPUT_TOKENS:
            data["max_tokens"] = MAX_OUTPUT_TOKENS

        # Log first request for debugging
        if not os.path.exists(DEBUG_LOG):
            try:
                msgs = data.get("messages", [])
                summary = []
                total_chars = 0
                for m in msgs:
                    role = m.get("role", "?")
                    content = m.get("content", "")
                    if isinstance(content, list):
                        content_str = json.dumps(content)
                    else:
                        content_str = str(content)
                    total_chars += len(content_str)
                    summary.append({
                        "role": role,
                        "chars": len(content_str),
                        "preview": content_str[:300],
                    })
                tools = data.get("tools", [])
                tool_names = [t.get("function", {}).get("name", "?") for t in tools]
                debug = {
                    "total_message_chars": total_chars,
                    "max_tokens_requested": data.get("max_tokens"),
                    "num_messages": len(msgs),
                    "num_tools": len(tools),
                    "tool_names": tool_names,
                    "messages_summary": summary,
                }
                with open(DEBUG_LOG, "w") as f:
                    json.dump(debug, f, indent=2, ensure_ascii=False)
            except Exception:
                pass

        return data

    async def async_post_call_success_hook(self, *args, **kwargs):
        pass

    async def async_post_call_failure_hook(self, *args, **kwargs):
        pass

    def log_success_event(self, *args, **kwargs):
        pass

    def log_failure_event(self, *args, **kwargs):
        pass


proxy_handler_instance = MaxTokensCapper()
