
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END

from .schemas import TravelState
from . import agents


def build_app():
    workflow = StateGraph(TravelState)

    workflow.add_node("orchestrator", agents.orchestrator_node)
    workflow.add_node("flight_agent", agents.flight_agent)
    workflow.add_node("hotel_agent", agents.hotel_agent)
    workflow.add_node("food_agent", agents.food_agent)
    workflow.add_node("attraction_agent", agents.attraction_agent)
    workflow.add_node("transport_agent", agents.transport_agent)
    workflow.add_node("aggregate", agents.aggregation_node)
    workflow.add_node("budget", agents.budget_agent)
    workflow.add_node("optimizer", agents.optimization_agent)
    workflow.add_node("final", agents.final_planner)
    workflow.add_node("critic", agents.critic_agent)
    workflow.add_node("guardrail", agents.guardrail_node)

    workflow.add_edge(START, "orchestrator")

    workflow.add_edge("orchestrator", "flight_agent")
    workflow.add_edge("orchestrator", "hotel_agent")
    workflow.add_edge("orchestrator", "food_agent")
    workflow.add_edge("orchestrator", "attraction_agent")
    workflow.add_edge("orchestrator", "transport_agent")

    workflow.add_edge("flight_agent", "aggregate")
    workflow.add_edge("hotel_agent", "aggregate")
    workflow.add_edge("food_agent", "aggregate")
    workflow.add_edge("attraction_agent", "aggregate")
    workflow.add_edge("transport_agent", "aggregate")

    workflow.add_edge("aggregate", "budget")

    workflow.add_conditional_edges(
        "budget", agents.budget_router, {"optimize": "optimizer", "finalize": "final"},
    )
    workflow.add_edge("optimizer", "budget")

    workflow.add_edge("final", "critic")
    workflow.add_conditional_edges(
        "critic", agents.critic_router, {"revise": "final", "done": "guardrail"},
    )
    workflow.add_edge("guardrail", END)

    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
