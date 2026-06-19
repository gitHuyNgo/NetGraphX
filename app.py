import os
import streamlit as st
import streamlit.components.v1 as components
from neo4j import GraphDatabase

from config.settings import neo4j_config
from src.rag.embedder import NodeEmbedder
from src.rag.query_parser import MultiIntentQueryParser
from src.rag.retriever import HybridRetriever
from src.rag.synthesizer import LLMSynthesizer

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="NetGraphX Dashboard",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# Cached Resources
# -----------------------------------------------------------------------------
@st.cache_resource
def get_neo4j_driver():
    """Initialises the Neo4j driver once."""
    return GraphDatabase.driver(
        neo4j_config.NEO4J_URI,
        auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD)
    )

@st.cache_resource
def get_embedder():
    """Initialises SentenceTransformers only once."""
    return NodeEmbedder()

@st.cache_resource
def get_query_parser():
    return MultiIntentQueryParser()

@st.cache_resource
def get_retriever(_driver, _embedder):
    return HybridRetriever(_driver, _embedder)

@st.cache_resource
def get_synthesizer():
    return LLMSynthesizer()

# -----------------------------------------------------------------------------
# App Layout
# -----------------------------------------------------------------------------
def main():
    st.title("NetGraphX Intelligence Dashboard")
    
    # Init cached components
    with st.spinner("Initialising RAG Engine & Database..."):
        driver = get_neo4j_driver()
        embedder = get_embedder()
        parser = get_query_parser()
        retriever = get_retriever(driver, embedder)
        synthesizer = get_synthesizer()

    # Create two columns: Graph (left/main) and Chatbot (right sidebar or col)
    # Using columns gives more space than the narrow sidebar.
    col_graph, col_chat = st.columns([2, 1])

    # -- LEFT COLUMN: TOPOLOGY GRAPH --
    with col_graph:
        st.subheader("Network Topology Graph")
        topology_path = "topology.html"
        
        if os.path.exists(topology_path):
            with open(topology_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            # Embed the Pyvis graph
            components.html(html_content, height=800, scrolling=True)
        else:
            st.warning("`topology.html` not found. Please run `python -m src.main` to generate the graph.")

    # -- RIGHT COLUMN: RAG CHATBOT --
    with col_chat:
        st.subheader("🤖 RAG Assistant")
        
        # Init chat history
        if "messages" not in st.session_state:
            st.session_state.messages = [
                {"role": "assistant", "content": "Xin chào! Tôi là trợ lý AI giám sát mạng lưới. Bạn muốn tra cứu thông tin hay kiểm tra lỗi gì?"}
            ]

        # Display chat history
        chat_container = st.container(height=650)
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        # Chat Input
        if prompt := st.chat_input("Hỏi trợ lý (VD: Liệt kê thiết bị SPOF)..."):
            # Display user message
            st.session_state.messages.append({"role": "user", "content": prompt})
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(prompt)

            # Generate AI Response
            with chat_container:
                with st.chat_message("assistant"):
                    with st.spinner("Đang phân tích..."):
                        try:
                            # 1. Parse intent
                            parsed_query = parser.parse(prompt)
                            
                            # 2. Retrieve
                            retrieval_results = retriever.retrieve(parsed_query)
                            
                            # 3. Synthesize
                            final_answer = synthesizer.synthesize(prompt, retrieval_results)
                            
                            st.markdown(final_answer)
                            st.session_state.messages.append({"role": "assistant", "content": final_answer})
                            
                            # Optional: Expander to show retrieved contexts
                            with st.expander("🔍 Xem dữ liệu truy xuất (Context)"):
                                for res in retrieval_results:
                                    st.write(f"**Intent:** `{res.intent.type}` / `{res.intent.target}`")
                                    st.text(res.context_text[:500] + ("..." if len(res.context_text) > 500 else ""))
                                    
                        except Exception as e:
                            error_msg = f"❌ Đã xảy ra lỗi: {str(e)}"
                            st.error(error_msg)
                            st.session_state.messages.append({"role": "assistant", "content": error_msg})

if __name__ == "__main__":
    main()
