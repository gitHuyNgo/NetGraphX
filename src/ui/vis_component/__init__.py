import os
import streamlit.components.v1 as components

_frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
_component_func = components.declare_component("vis_network", path=_frontend_dir)

def vis_network(html: str, height: int = 460, highlight: str = None, key=None):
    """
    Renders an interactive vis.js HTML string and returns the ID of the clicked node.
    """
    return _component_func(html=html, height=height, highlight=highlight, key=key, default=None)
