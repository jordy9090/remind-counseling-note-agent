"""Compatibility wrapper for the current Re:mind note graph."""
from app.graph.graph import create_note_graph


def create_workflow():
    return create_note_graph()


app = create_workflow()
