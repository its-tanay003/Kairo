"""
Verification script for LlamaCppClient with constrained JSON schema output.
"""
from orchestrator.llama_client import LlamaCppClient
from registry.loader import ToolRegistry

def test():
    reg = ToolRegistry()
    client = LlamaCppClient()
    print("Checking llama-server health:", client.is_healthy())
    assert client.is_healthy(), "llama-server must be running at http://127.0.0.1:8080"

    print("\n--- Testing Tool Call Prompt ---")
    resp_tool = client.generate_constrained("Please execute hello_world tool for Tanay", reg.list_tools())
    print("Action:", resp_tool.action)
    print("Is Tool Call:", resp_tool.is_tool_call())
    print("Tool Call Payload:", resp_tool.tool_call)

    print("\n--- Testing Conversational Message Prompt ---")
    resp_msg = client.generate_constrained("Hello, how are you today?", reg.list_tools())
    print("Action:", resp_msg.action)
    print("Content:", resp_msg.content)
    print("Tool Call Payload:", resp_msg.tool_call)

if __name__ == "__main__":
    test()
