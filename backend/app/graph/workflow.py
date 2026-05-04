"""LangGraph 워크플로우 정의"""
from langgraph.graph import StateGraph, END
from app.graph.state import GraphState
from app.graph.nodes.structure_node import structure_node
from app.graph.nodes.summary_node import summary_node
from app.graph.nodes.verification_node import verification_node


def create_workflow():
    """
    LangGraph 워크플로우 생성
    
    Flow:
    structure_node → summary_node → verification_node → END
    """
    workflow = StateGraph(GraphState)
    
    # 노드 추가
    workflow.add_node("structure", structure_node)
    workflow.add_node("summary", summary_node)
    workflow.add_node("verification", verification_node)
    
    # 엣지 추가 (노드 연결)
    workflow.add_edge("structure", "summary")
    workflow.add_edge("summary", "verification")
    workflow.add_edge("verification", END)
    
    # 시작 노드 설정
    workflow.set_entry_point("structure")
    
    # 워크플로우 컴파일
    return workflow.compile()


# 전역 워크플로우 인스턴스
app = create_workflow()
