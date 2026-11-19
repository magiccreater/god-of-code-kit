"""Translate stateless text and function tools to Chat Completions."""
from http.client import HTTPException
import json
import time
import uuid


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(part, dict)
            and part.get("type") in ("input_text", "output_text", "text")
            and isinstance(part.get("text"), str) for part in content):
        return "\n".join(part["text"] for part in content)
    raise ValueError("Unsupported text content")


def chat_tool(tool):
    function = {key: tool[key] for key in ("name", "description", "parameters", "strict") if key in tool}
    return {"type": "function", "function": function}


def chat_request(body, model):
    messages = []
    if body.get("instructions"):
        messages.append({"role": "system", "content": text_content(body["instructions"])})
    items = body.get("input", [])
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    if not isinstance(items, list):
        raise ValueError("Expected a list of input items")
    pending_calls = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid input item")
        kind = item.get("type", "message")
        if kind == "function_call":
            pending_calls.append({
                "id": item["call_id"], "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"]},
            })
            continue
        if pending_calls:
            messages.append({"role": "assistant", "content": None, "tool_calls": pending_calls})
            pending_calls = []
        if kind == "message":
            role = item.get("role")
            if role not in ("developer", "system", "user", "assistant"):
                raise ValueError("Unsupported message role")
            messages.append({"role": "system" if role == "developer" else role,
                             "content": text_content(item["content"])})
        elif kind == "function_call_output":
            messages.append({"role": "tool", "tool_call_id": item["call_id"],
                             "content": text_content(item["output"])})
        else:
            raise ValueError("Unsupported input item")
    if pending_calls:
        messages.append({"role": "assistant", "content": None, "tool_calls": pending_calls})
    format_type = (body.get("text") or {}).get("format", {}).get("type", "text")
    if format_type != "text" or not messages:
        raise ValueError("Gateway requires a text conversation")
    request = {"model": model, "messages": messages, "stream": body.get("stream", False)}
    if "max_output_tokens" in body:
        request["max_tokens"] = body["max_output_tokens"]
    if body.get("tools"):
        request["tools"] = [chat_tool(tool) for tool in body["tools"]]
    return request


def base_response(model):
    return {
        "id": "resp_" + uuid.uuid4().hex, "object": "response", "model": model,
        "created_at": int(time.time()), "status": "in_progress", "output": [],
    }


def message_item(text, item_id=None, status="completed"):
    return {"type": "message", "id": item_id or "msg_" + uuid.uuid4().hex, "role": "assistant",
            "status": status, "content": [{"type": "output_text", "text": text, "annotations": []}]}


def function_item(call_id, name, arguments):
    if not all(isinstance(value, str) and value for value in (call_id, name, arguments)):
        raise ValueError("Incomplete function call")
    parsed = json.loads(arguments)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid function arguments")
    return {"type": "function_call", "id": "fc_" + uuid.uuid4().hex, "status": "completed",
            "call_id": call_id, "name": name, "arguments": arguments}


def usage_details(usage):
    inputs = usage.get("prompt_tokens", 0)
    outputs = usage.get("completion_tokens", 0)
    return {"input_tokens": inputs, "output_tokens": outputs,
            "total_tokens": usage.get("total_tokens", inputs + outputs)}


def complete_response(body, model):
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Chat completion has no choices")
    choice = choices[0]
    if choice["finish_reason"] not in ("stop", "tool_calls"):
        raise ValueError("Chat completion did not finish")
    message = choice["message"]
    if bool(message.get("tool_calls")) != (choice["finish_reason"] == "tool_calls"):
        raise ValueError("Chat completion did not return a complete tool or message")
    response = base_response(model)
    if message.get("content"):
        response["output"].append(message_item(text_content(message["content"])))
    for call in message.get("tool_calls", []):
        response["output"].append(function_item(
            call["id"], call["function"]["name"], call["function"]["arguments"]))
    response.update(status="completed", usage=usage_details(body.get("usage") or {}))
    return response


def sse(kind, **fields):
    body = json.dumps({"type": kind, **fields}, separators=(",", ":"), ensure_ascii=False)
    return f"event: {kind}\ndata: {body}\n\n".encode()


def response_events(upstream, model):
    response = base_response(model)
    yield sse("response.created", response=response)
    text_parts = []
    message_id = "msg_" + uuid.uuid4().hex
    calls = {}
    usage = {}
    reason = None
    complete = False
    try:
        while line := upstream.readline(262145):
            if len(line) > 262144:
                raise ValueError("Upstream event too large")
            line = line.strip()
            if line == b"data: [DONE]":
                complete = True
                break
            if not line.startswith(b"data: "):
                continue
            event = json.loads(line[6:])
            if event.get("error"):
                raise ValueError("Upstream error event")
            if event.get("usage"):
                usage = event["usage"]
            for choice in event.get("choices", []):
                if choice.get("index", 0) != 0:
                    continue
                reason = choice.get("finish_reason") or reason
                delta = choice.get("delta") or {}
                if text := delta.get("content"):
                    if not isinstance(text, str):
                        raise ValueError("Invalid text delta")
                    if not text_parts:
                        item = message_item("", message_id, "in_progress")
                        yield sse("response.output_item.added", output_index=0, item={**item, "content": []})
                        yield sse("response.content_part.added", item_id=message_id, output_index=0,
                                  content_index=0, part=item["content"][0])
                    text_parts.append(text)
                    yield sse("response.output_text.delta", item_id=message_id, output_index=0,
                              content_index=0, delta=text)
                for segment in delta.get("tool_calls", []):
                    call = calls.setdefault(segment["index"], {"id": "", "name": "", "arguments": ""})
                    if segment.get("id"):
                        call["id"] = segment["id"]
                    details = segment.get("function") or {}
                    for key in ("name", "arguments"):
                        call[key] += details.get(key) or ""
        if not complete or reason not in ("stop", "tool_calls") or bool(calls) != (reason == "tool_calls"):
            raise ValueError("Chat stream ended without a complete tool or message")
        # Validate every call before exposing any call to the worker.
        tool_items = [function_item(call["id"], call["name"], call["arguments"])
                      for _, call in sorted(calls.items())]
        if text_parts:
            text = "".join(text_parts)
            item = message_item(text, message_id)
            response["output"].append(item)
            yield sse("response.output_text.done", item_id=message_id, output_index=0,
                      content_index=0, text=text)
            yield sse("response.content_part.done", item_id=message_id, output_index=0,
                      content_index=0, part=item["content"][0])
            yield sse("response.output_item.done", output_index=0, item=item)
        for item in tool_items:
            index = len(response["output"])
            response["output"].append(item)
            yield sse("response.output_item.added", output_index=index,
                      item={**item, "status": "in_progress", "arguments": ""})
            yield sse("response.function_call_arguments.done", item_id=item["id"],
                      output_index=index, arguments=item["arguments"], name=item["name"])
            yield sse("response.output_item.done", output_index=index, item=item)
        response.update(status="completed", usage=usage_details(usage))
        yield sse("response.completed", response=response)
    except (AttributeError, HTTPException, KeyError, OSError, TypeError, ValueError):
        response.update(status="failed", error={
            "code": "server_error", "message": "AWS inference stream ended without a usable result.",
        })
        yield sse("response.failed", response=response)
