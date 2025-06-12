import streamlit as st
from supabase import create_client, Client
import os
import sys
import time
import random
import traceback
import re
import tempfile

# --- Page Configuration (MUST be the first and ONLY command) ---
st.set_page_config(page_title="InsightRFQ - Think Tank", page_icon="assets/thinktank_logo.png", layout="wide", initial_sidebar_state="expanded")

# --- THEME DEFINITION ---
if 'theme' not in st.session_state: st.session_state.theme = 'light'
TT_FOUNTAIN_BLUE, TT_SCARPA_FLOW, TT_JUMBO, TT_SILVER_SAND = "#4ca4bc", "#2E3035", "#888B92", "#EAEBF0"
light_theme = { "accent": TT_FOUNTAIN_BLUE, "primary_bg": "#FFFFFF", "secondary_bg": "#F0F2F6", "sidebar_bg": "#F8F9FA", "text_primary": "#1E1E1E", "text_secondary": "#59595B", "logo_filter": "none", "chat_bubble_bg": "#FFFFFF" }
dark_theme = { "accent": TT_FOUNTAIN_BLUE, "primary_bg": "#1E1F22", "secondary_bg": "#2E3035", "sidebar_bg": TT_SCARPA_FLOW, "text_primary": TT_SILVER_SAND, "text_secondary": TT_JUMBO, "logo_filter": "brightness(0) saturate(100%) invert(91%) sepia(6%) saturate(301%) hue-rotate(180deg) brightness(108%) contrast(91%)", "chat_bubble_bg": "#2E3035" }
theme = light_theme

# --- SUPABASE CONNECTION ---
@st.cache_resource
def init_supabase_client():
    try: url = st.secrets["supabase"]["url"]; key = st.secrets["supabase"]["key"]; return create_client(url, key)
    except Exception as e: st.error(f"Supabase connection failed: {e}. Check secrets.toml."); return None
supabase: Client = init_supabase_client()

# --- AUTHENTICATION & SESSION STATE INITIALIZATION ---
if 'user' not in st.session_state: st.session_state.user = None
if 'messages' not in st.session_state: st.session_state.messages = []
if 'chat_history' not in st.session_state: st.session_state.chat_history = {}
if 'current_chat_id' not in st.session_state: st.session_state.current_chat_id = None
if 'uploaded_file_vs' not in st.session_state: st.session_state.uploaded_file_vs = None
if 'uploaded_file_name' not in st.session_state: st.session_state.uploaded_file_name = None

# --- LOGIN PAGE UI ---
if st.session_state.user is None:
    st.markdown(f"""<style>[data-testid="stSidebar"] {{ display: none; }} .main > div {{ max-width: 600px; margin: auto; padding-top: 3rem; }} .stTabs [data-baseweb="tab-list"] {{ justify-content: center; }} .stButton>button {{ width: 100%; }}</style>""", unsafe_allow_html=True)
    col1, col2 = st.columns([1.5, 1])
    with col1:
        st.image("assets/thinktank_logo.png", width=300); st.title("AI-Powered RFP/RFQ Assistant"); st.markdown("### Your competitive advantage."); st.markdown("- Instantly **summarize** docs.\n- **Extract** requirements.\n- **Generate** BOMs.")
    with col2:
        st.header("Welcome"); login_tab, signup_tab = st.tabs(["🔒 Login", "✍️ Sign Up"])
        with login_tab:
            with st.form("login_form"):
                email = st.text_input("Email"); password = st.text_input("Password", type="password")
                if st.form_submit_button("Log In & Analyze", type="primary"):
                    if supabase:
                        try: user_session = supabase.auth.sign_in_with_password({"email": email, "password": password}); st.session_state.user = user_session.user; st.rerun()
                        except: st.error("Login failed. Check credentials.")
        with signup_tab:
            with st.form("signup_form"):
                new_email = st.text_input("Email"); new_password = st.text_input("Password", type="password")
                if st.form_submit_button("Sign Up", type="primary"):
                    if supabase:
                        try: user = supabase.auth.sign_up({"email": new_email, "password": new_password}); st.success("Signup successful! Please proceed to Login."); st.balloons()
                        except: st.error("Signup failed. Email may be in use.")
else:
    # --- MAIN APPLICATION UI ---
    
    # --- Backend Integration & Variable Definitions ---
    backend_initialized_successfully = False
    llm_from_backend, vector_store_from_backend, RFP_PROMPT_obj, perform_manual_rag_query_func, INDEXED_RFP_FILES, embeddings_from_backend = None, None, None, None, [], None
    try:
        import rag_core_turbo
        from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
        from langchain.text_splitter import RecursiveCharacterTextSplitter
        from langchain_community.vectorstores import FAISS
        llm_from_backend, vector_store_from_backend, RFP_PROMPT_obj, perform_manual_rag_query_func, embeddings_from_backend = rag_core_turbo.llm, rag_core_turbo.vector_store_for_manual_rag, rag_core_turbo.RFP_PROMPT, rag_core_turbo.perform_manual_rag_query, rag_core_turbo.embeddings_client
        INDEXED_RFP_FILES = [os.path.basename(f) for f in rag_core_turbo.rfp_files_to_process] if hasattr(rag_core_turbo, 'rfp_files_to_process') and rag_core_turbo.rfp_files_to_process else ["RFB 3059-2024.docx", "Tender RFQ 02 2024.pdf"]
        backend_initialized_successfully = True
    except Exception as e: backend_initialized_successfully = False; print(f"UI_DEBUG: BACKEND INIT ERROR - {e}")

    LOGO_B64_STRING = "data:image/png;base64,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"

    # --- Professional CSS ---
    st.markdown(f"""
    <style>
        :root {{
            --accent: {theme['accent']}; --primary-bg: {theme['primary_bg']}; --secondary-bg: {theme['secondary_bg']};
            --sidebar-bg: {theme['sidebar_bg']}; --text-primary: {theme['text_primary']}; --text-secondary: {theme['text_secondary']};
            --logo-filter: {theme['logo_filter']}; --chat-bubble-bg: {theme['chat_bubble_bg']};
        }}
        .stApp > header, footer {{ display: none; }}
        .main {{ background-image: linear-gradient(to bottom right, var(--primary-bg), var(--secondary-bg)); }}
        [data-testid="stSidebar"] {{ background-color: var(--sidebar-bg); border-right: 1px solid var(--secondary-bg); }}
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] li {{ color: var(--text-primary) !important; }}
        [data-testid="stSidebar"] h3 {{ color: var(--accent) !important; text-transform: uppercase; font-size: 0.9em; }}
        #logo-background {{ background-color: var(--secondary-bg); border-radius: 10px; padding: 1rem; margin: 1rem; }}
        #logo-background img {{ filter: var(--logo-filter); width: 100%; }}
        .user-badge {{ background-color: var(--secondary-bg); padding: 0.5rem 0.75rem; border-radius: 0.5rem; margin-bottom: 1rem; }}
        .user-badge p, .user-badge small {{ color: var(--text-primary) !important; margin: 0; }}
        div[data-testid="stChatMessage"] > div[data-testid*="stChatMessageContent"] {{ background-color: var(--chat-bubble-bg); color: var(--text-primary); }}
        div[data-testid="stChatMessage"] p, div[data-testid="stChatMessage"] li, div[data-testid="stChatMessage"] h3, div[data-testid="stChatMessage"] strong {{ color: var(--text-primary) !important; }}
    </style>
    """, unsafe_allow_html=True)

    # --- Sidebar Content ---
    with st.sidebar:
        st.markdown(f"<div id='logo-background'><img src='{LOGO_B64_STRING}' alt='Think Tank Logo'></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='user-badge'><p>Welcome!</p><small>{st.session_state.user.email}</small></div>", unsafe_allow_html=True)
        if st.button("Logout", use_container_width=True):
            if st.session_state.messages and st.session_state.current_chat_id: st.session_state.chat_history[st.session_state.current_chat_id] = st.session_state.messages
            st.session_state.user = None; st.rerun()
        
        
        
        st.subheader("Chat History")
        if st.button("➕ New Chat", use_container_width=True):
            if st.session_state.messages and st.session_state.current_chat_id: st.session_state.chat_history[st.session_state.current_chat_id] = st.session_state.messages
            st.session_state.messages, st.session_state.current_chat_id = [], None; st.rerun()
        sorted_chat_ids = sorted(st.session_state.chat_history.keys(), reverse=True)
        for chat_id in sorted_chat_ids:
            chat_title = st.session_state.chat_history[chat_id][1]['content'][:30] + "..." if len(st.session_state.chat_history[chat_id]) > 1 else f"Chat from {time.strftime('%b %d', time.localtime(int(chat_id.split('_')[1])))}"
            if st.button(chat_title, key=chat_id, use_container_width=True, type="secondary"):
                if st.session_state.messages and st.session_state.current_chat_id and st.session_state.current_chat_id != chat_id: st.session_state.chat_history[st.session_state.current_chat_id] = st.session_state.messages
                st.session_state.messages, st.session_state.current_chat_id = st.session_state.chat_history[chat_id], chat_id; st.rerun()
        st.markdown("---")
        
        if backend_initialized_successfully: st.success("✅ Backend Connected")
        else: st.error("⚠️ Backend Connection Error")
        st.subheader("Upload a Document"); uploaded_file = st.file_uploader("Upload PDF or DOCX", type=["pdf", "docx"], label_visibility="collapsed")
        if uploaded_file and uploaded_file.name != st.session_state.uploaded_file_name:
            with st.spinner(f"Processing {uploaded_file.name}..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue()); temp_file_path = tmp_file.name
                try:
                    loader = PyPDFLoader(temp_file_path) if uploaded_file.type == "application/pdf" else Docx2txtLoader(temp_file_path)
                    docs = loader.load(); splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
                    splits = splitter.split_documents(docs); st.session_state.uploaded_file_vs = FAISS.from_documents(splits, embeddings_from_backend)
                    st.session_state.uploaded_file_name = uploaded_file.name; st.success(f"✅ Ready: '{uploaded_file.name}'")
                except Exception as e: st.error(f"Failed to process file: {e}")
                finally:
                    if os.path.exists(temp_file_path): os.remove(temp_file_path)
        st.subheader("Indexed Documents")
        for rfp_file in INDEXED_RFP_FILES: st.markdown(f"📄 _{rfp_file}_")
        st.markdown("---")
        st.subheader("Focus Analysis")
        focus_options = ["All Indexed Documents"] + INDEXED_RFP_FILES
        if st.session_state.uploaded_file_name: focus_options.append(st.session_state.uploaded_file_name)
        st.selectbox("Analyze:", options=focus_options, key="doc_focus_select"); st.markdown("---")
        st.subheader("Example Questions")
        example_questions = {"SITA: Purpose": "Summarize SITA RFQ.", "Wits: Tech Reqs": "List tech reqs for Wits Tender."}
        for display_text, query_text in example_questions.items():
            if st.button(display_text, key=f"ex_{display_text}", use_container_width=True): st.session_state.run_query = query_text; st.rerun()

    # --- Main Chat Interface ---
    st.markdown(f"<h1 style='color: var(--text-primary);'>🤖 InsightRFQ/RFP</h1>", unsafe_allow_html=True)
    if not st.session_state.messages: st.session_state.messages.append({"role": "assistant", "content": "Hello! Start a new chat or ask about your documents."})

    for i, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and i > 0:
                with st.expander("View Sources, Actions & Follow-ups"):
                    if "sources_markdown" in message and message["sources_markdown"]: st.markdown("**Sources:**"); st.markdown(message["sources_markdown"], unsafe_allow_html=True); st.markdown("---")
                    st.markdown("**Copy Raw Answer:**"); st.code(message.get("raw_content", message["content"]), language=None)
                    if "suggested_questions" in message and message["suggested_questions"]:
                        st.markdown("**Suggested Follow-ups:**")
                        if message["suggested_questions"]:
                            cols = st.columns(len(message["suggested_questions"]))
                            for j, q_text in enumerate(message["suggested_questions"]):
                                if cols[j].button(q_text, key=f"suggested_{i}_{j}", use_container_width=True): st.session_state.run_query = q_text; st.rerun()

    query_to_process = st.session_state.pop('run_query', None)
    if not query_to_process: query_to_process = st.chat_input("Ask your question...")

    if query_to_process:
        st.session_state.messages.append({"role": "user", "content": query_to_process})
        if st.session_state.current_chat_id is None: st.session_state.current_chat_id = f"chat_{int(time.time())}"
        st.rerun()

    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
        user_query = st.session_state.messages[-1]["content"]
        with st.chat_message("assistant"):
            message_placeholder = st.empty()
            with st.spinner("🤖 Analyzing..."):
                if not perform_manual_rag_query_func:
                    bot_answer_content, sources_display_md, suggested_questions = "Error: Backend is not available.", "", []
                else:
                    try:
                        doc_focus_value = st.session_state.get('doc_focus_select', "All Indexed Documents")
                        current_vector_store, target_doc = vector_store_from_backend, doc_focus_value if doc_focus_value != "All Indexed Documents" else None
                        if doc_focus_value == st.session_state.uploaded_file_name and st.session_state.uploaded_file_vs:
                            current_vector_store, target_doc = st.session_state.uploaded_file_vs, None
                        response_data = perform_manual_rag_query_func(user_query, current_vector_store, llm_from_backend, RFP_PROMPT_obj, target_document_name=target_doc)
                        bot_answer_content, sources = response_data.get("answer", "I couldn't find an answer."), response_data.get("sources_for_ui", [])
                        sources_display_md = ""
                        if sources: md_parts = [f"> {src.get('content_snippet', 'N/A')[:200]}...\n> *Source: `{src.get('source_document', 'N/A')}`*" for src in sources]; sources_display_md = "\n\n".join(md_parts)
                        suggested_questions = ["Summarize key deadlines", "List all compliance requirements"]
                    except Exception as e: bot_answer_content, sources_display_md, suggested_questions = f"An error occurred: {e}", "", []; traceback.print_exc()
            
            # ### THE DEFINITIVE FORMATTING FIX ###
            # This is the correct way to handle streaming and Markdown rendering.
            
            # Animate the response word-by-word for a dynamic effect
            animated_response = ""
            for chunk in bot_answer_content.split():
                animated_response += chunk + " "
                time.sleep(0.02)
                # Display plain text with a cursor during animation
                message_placeholder.markdown(animated_response + "▌")

            # Final render: After the loop, render the complete Markdown string properly.
            message_placeholder.markdown(bot_answer_content)
        
        # We store the raw, unformatted answer from the bot in the session state
        # This is what the Copy button will use, and what we will display.
        # The prompt in rag_core_turbo.py will ensure it's already well-formatted Markdown.
        assistant_message_data = {
            "role": "assistant",
            "content": bot_answer_content, # Store the clean, raw Markdown
            "raw_content": bot_answer_content, # Also use the raw for the copy button
            "sources_markdown": sources_display_md,
            "suggested_questions": suggested_questions
        }
        st.session_state.messages.append(assistant_message_data)
        if st.session_state.current_chat_id: st.session_state.chat_history[st.session_state.current_chat_id] = st.session_state.messages
        st.rerun()

    if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
        st.markdown("---")
        feedback_cols = st.columns([1, 1, 10])
        with feedback_cols[0]:
            if st.button("👍", key=f"helpful_{len(st.session_state.messages)}"): st.toast("Thanks!", icon="😊")
        with feedback_cols[1]:
            if st.button("👎", key=f"unhelpful_{len(st.session_state.messages)}"): st.toast("Thanks, we'll improve.", icon="🛠️")