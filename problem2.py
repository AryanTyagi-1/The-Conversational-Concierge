import os
import asyncio
import requests
from langgraph.graph import StateGraph, START, END, MessagesState
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from openai import OpenAI
from typing import Literal


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


DOCUMENTS = [
    "Napa Valley produces world-class Cabernet Sauvignon and Chardonnay wines.",
    "The winery offers daily vineyard tours and tastings from 10 AM to 6 PM.",
    "Our wine shop has exclusive imports and limited edition vintages."
]


def retrieve_relevant_docs(query: str):
    
    keywords = query.lower().split()
    results = []
    for doc in DOCUMENTS:
        if any(kw in doc.lower() for kw in keywords):
            results.append(doc)
    return results if results else DOCUMENTS[:1]  


def get_weather(args: dict) -> str:
    location = args.get("location", "Napa Valley,CA")
    url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={WEATHER_API_KEY}&units=imperial"
    try:
        resp = requests.get(url)
        data = resp.json()
        description = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        return f"Weather in {location} is {description} with temperature {temp} °F."
    except Exception as e:
        return f"Failed to fetch weather: {e}"


def web_search(args: dict) -> str:
    query = args.get("query", "")
    
    if "price" in query.lower():
        return "Average Napa Valley wine bottle price is $45."
    if "event" in query.lower():
        return "Next wine tasting event is on Saturday evening."
    if "tour" in query.lower():
        return "Tours are available everyday between 10AM and 6PM."
    return "No recent info available for your search query."


def llm_call(state: MessagesState):
    messages = state["messages"]

    
    user_msg = next((m for m in reversed(messages) if m.type == "human"), None)
    if not user_msg:
        return {"messages": messages}

    text = user_msg.content.lower()

    
    tool_call = None
    if "weather" in text:
        tool_call = {"name": "get_weather", "args": {"location": "Napa Valley,CA"}}
    elif any(keyword in text for keyword in ["price", "event", "tour", "latest"]):
        tool_call = {"name": "web_search", "args": {"query": text}}
    else:
        
        relevant_docs = retrieve_relevant_docs(user_msg.content)
        context_text = "\n".join(f"- {d}" for d in relevant_docs)
        prompt = f"You are a helpful assistant for a Napa Valley wine business.\nContext:\n{context_text}\n\nUser question: {user_msg.content}\nAnswer:"
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            temperature=0.3,
            max_tokens=256
        )
        answer = response.choices[0].message.content
        
        return {"messages": messages + [HumanMessage(content=answer)]}

    
    new_msg = ToolMessage(content="", tool_calls=[tool_call])
    return {"messages": messages + [new_msg]}


def tool_node(state: dict):
    messages = state["messages"]
    last_msg = messages[-1]
    tool_msgs = []

    for tool_call in last_msg.tool_calls:
        if tool_call["name"] == "get_weather":
            output = get_weather(tool_call["args"])
        elif tool_call["name"] == "web_search":
            output = web_search(tool_call["args"])
        else:
            output = f"Unknown tool: {tool_call['name']}"

        tool_msgs.append(ToolMessage(content=output, tool_call_id=tool_call.get("id", None)))

    return {"messages": messages[:-1] + tool_msgs}


def should_continue(state: MessagesState) -> Literal["Tool", END]:
    last_message = state["messages"][-1]
    if last_message.type == "tool" and last_message.tool_calls:
        return "Tool"
    if last_message.type == "tool":
        
        return "LLM"
    
    return END


agent_builder = StateGraph(MessagesState)

agent_builder.add_node("LLM", llm_call)
agent_builder.add_node("Tool", tool_node)
agent_builder.add_edge(START, "LLM")
agent_builder.add_conditional_edges(
    "LLM",
    should_continue,
    {"Tool": "Tool", END: END},
)
agent_builder.add_edge("Tool", "LLM")

agent = agent_builder.compile()


async def main():
    print("Welcome to the Napa Valley Wine Concierge (LangGraph powered). Type 'quit' to exit.")
    messages = []
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["quit", "exit"]:
            print("Goodbye!")
            break

        messages.append(HumanMessage(content=user_input))
        state = {"messages": messages}
        result = agent.invoke_sync(state)
        messages = result["messages"]

        
        last_msg = messages[-1]
        if last_msg.type == "human":
            print("Agent:", last_msg.content)
        else:
            print("Agent: (continuing...)")

if __name__ == "__main__":
    asyncio.run(main())
