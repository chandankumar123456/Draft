from credential import openai_client, project_client
from azure.ai.projects.models import PromptAgentDefinition, WebSearchTool
from instructions import instructions
from openai.types.responses.response_input_param import ResponseInputParam, FunctionCallOutput

from dotenv import load_dotenv
import os
import json
load_dotenv()

from tools.tools import list_files_tool

agent = project_client.agents.create_version(
    agent_name="Draft-Main-Agent",
    definition=PromptAgentDefinition(
        model = os.getenv("MODEL_DEPLOYMENT"),
        instructions=instructions,
        tools=[WebSearchTool(), list_files_tool]
    )
)

# create a conversation thread
conversation = openai_client.conversations.create()
input_list:ResponseInputParam = []

# ----- delete below later
# print("\n=== ResponseInputParam ===")
# print("Type:", type(input_list))
# print("Value:", input_list)
# print("Is list:", isinstance(input_list, list))
# print()
# ----- delete above later

while True:
    user_input = input("Enter a prompt for the Draft-Main-Agent. use 'quit' to exit.\nUser: ").strip()
    if user_input.strip() == "quit":
        break

    # send prompt to the model
    openai_client.conversations.items.create(
        conversation_id=conversation.id,
        items = [
            {
                "type": "message",
                "role": "user",
                "content": user_input
            }
        ]
    )

    response = openai_client.responses.create(
        conversation=conversation.id,
        extra_body= {
            "agent_reference": {
                "name": agent.name,
                "type": "agent_reference"
            }
        }, 
        input = input_list
    )

    if response.status == "failed":
                    print(f"Response Failed: {response.error}")
                    
                    
    for item in response.output:
        # print("\n", item)
        if item.type == "function_call":
            # retrieve the matching function
            function_name = item.name
            result = None
            if item.name == "list_files":
                from tools.functions import list_files
                result = list_files(**json.loads(item.arguments))    
                
            # append the output text
            input_list.append(
                FunctionCallOutput(
                    type = "function_call_output",
                    call_id=item.call_id,
                    output = json.dumps(result)
                )
            )
            
            
            # ---- delete below later
            # print("\n=== FUNCTION CALL ===")
            # print("Item type:", item.type)
            # print("Function name:", item.name)
            # print("Call ID:", item.call_id)
            # print("Arguments:", item.arguments)
            # print("Parsed arguments:", json.loads(item.arguments))
            # print("Function result:", result)
            # print("Result type:", type(result))
            # print("input list: ", input_list)
            # ---- delete above later

    if input_list:
        response = openai_client.responses.create(
            input = input_list,
            previous_response_id=response.id,
            extra_body={
                "agent_reference": {
                    "name": agent.name,
                    "type": "agent_reference"
                }
            }
        )
        
        # display the agent's response
        print(f"AGENT: {response.output_text}")
            

project_client.agents.delete_version(
    agent_name = agent.name,
    agent_version=agent.version
)
        
print("Agent Deleted")