from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agents.prompts import SYSTEM_PROMPT, format_rag_user_message
from app.services.retrieval import search as retrieve_context
from app.utils.llm import llm_client


def lc_messages_to_openai(messages: list[AnyMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        t = m.type
        if t == "human":
            role = "user"
        elif t == "ai":
            role = "assistant"
        elif t == "system":
            role = "system"
        else:
            role = "user"
        out.append({"role": role, "content": str(m.content)})
    return out


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    context: str
    doc_id: str
    sources: list[dict[str, Any]]


UNKNOWN_REPLY = "I cannot find this information in the uploaded document."


async def retrieve(state: AgentState) -> dict[str, Any]:
    messages = state["messages"]
    doc_id = state["doc_id"]
    if not messages:
        return {"context": "", "sources": []}
    last = messages[-1]
    if not isinstance(last, HumanMessage):
        return {"context": "", "sources": []}
    query = str(last.content)
    context, sources = await retrieve_context(query, doc_id, n_results=6)
    if not context.strip():
        return {"context": "", "sources": []}
    return {"context": context, "sources": sources}


async def generate(state: AgentState) -> dict[str, Any]:
    messages = list(state["messages"])
    context = (state.get("context") or "").strip()
    if not context:
        return {"messages": [AIMessage(content=UNKNOWN_REPLY)]}

    if not messages or not isinstance(messages[-1], HumanMessage):
        return {"messages": [AIMessage(content=UNKNOWN_REPLY)]}

    user_question = str(messages[-1].content)
    rag_user = format_rag_user_message(context=context, question=user_question)

    prior = messages[:-1]
    tail = prior[-5:] if len(prior) > 5 else prior
    lc_messages: list[AnyMessage] = [SystemMessage(content=SYSTEM_PROMPT)] + tail + [
        HumanMessage(content=rag_user)
    ]
    openai_msgs = lc_messages_to_openai(lc_messages)
    text = await llm_client.chat(openai_msgs)
    return {"messages": [AIMessage(content=text)]}


def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph


class RiskAuditorAgent:
    def __init__(self) -> None:
        self.graph = _build_graph()
        self.checkpointer: Any = None

    async def chat(
        self,
        message: str,
        thread_id: str,
        doc_id: str,
    ) -> dict[str, Any]:
        compiled = self.graph.compile(checkpointer=self.checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        payload: AgentState = {
            "messages": [HumanMessage(content=message)],
            "doc_id": doc_id,
            "context": "",
            "sources": [],
        }
        result = await compiled.ainvoke(payload, config)
        msgs = result.get("messages") or []
        reply = ""
        for m in reversed(msgs):
            if isinstance(m, AIMessage):
                reply = str(m.content)
                break
        return {
            "reply": reply,
            "sources": result.get("sources") or [],
            "thread_id": thread_id,
        }

    async def record_streamed_turn(
        self,
        thread_id: str,
        doc_id: str,
        user: str,
        assistant: str,
        context: str,
        sources: list[dict[str, Any]],
    ) -> None:
        """Persist a user/assistant exchange after streaming generation outside the graph."""
        if self.checkpointer is None:
            return
        compiled = self.graph.compile(checkpointer=self.checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        await compiled.aupdate_state(
            config,
            {
                "messages": [HumanMessage(content=user), AIMessage(content=assistant)],
                "doc_id": doc_id,
                "context": context,
                "sources": sources,
            },
        )

agent = RiskAuditorAgent()
