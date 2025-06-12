# rag_core_turbo.py

import os
from dotenv import load_dotenv
load_dotenv()
import hashlib
import traceback
import tempfile
from docx import Document
from azure.core.credentials import AzureKeyCredential
from azure.storage.blob import BlobServiceClient
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex, SearchField, SearchFieldDataType,
    SimpleField, SearchableField, VectorSearch,
    HnswAlgorithmConfiguration, VectorSearchProfile
)
from azure.ai.formrecognizer import DocumentAnalysisClient
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.prompts import PromptTemplate
from langchain_community.vectorstores.azuresearch import AzureSearch

# --- Global Variables & Clients ---
EMBEDDING_DIMENSIONS = 0
embeddings_client = None
llm = None
vector_store_for_manual_rag = None
RFP_PROMPT = None

# List of expected files in Blob Storage
rfp_files_expected_in_blob = [
    "RFB 3059-2024 Bid Specification.docx",
    "Tender Document for RFQ 02 2024 SITA RFB 1183 2022 - Provision of Provincial Support Services for DOJCD.pdf",
    "Wits Tender 2025 04 ICT - Information Technology Service Management (ITSM) System Annexure B Returnable Schedule.docx"
]

print("--- Initializing RAG Core Turbo Backend Components ---")

# --- Initialize Embedding Client ---
try:
    AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
    if not all([AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_EMBEDDING_DEPLOYMENT]):
        raise ValueError("One or more Azure OpenAI Embedding environment variables are missing.")
    print(f"Attempting to use Azure OpenAI Embeddings: {AZURE_OPENAI_EMBEDDING_DEPLOYMENT}")
    embeddings_client = AzureOpenAIEmbeddings(
        azure_deployment=AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        openai_api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY
    )
    _ = embeddings_client.embed_query("test")
    EMBEDDING_DIMENSIONS = 1536
    print("✅ Successfully initialized Azure OpenAI Embeddings.")
except Exception as e:
    print(f"❌ CRITICAL ERROR initializing Azure OpenAI Embeddings: {e}")
    embeddings_client = None

# --- Initialize LLM Client ---
try:
    AZURE_OPENAI_CHAT_DEPLOYMENT = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
    if not all([AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_CHAT_DEPLOYMENT]):
        raise ValueError("One or more Azure OpenAI Chat environment variables are missing.")
    print(f"Attempting to use Azure OpenAI Chat Model: {AZURE_OPENAI_CHAT_DEPLOYMENT}")
    llm = AzureChatOpenAI(
        azure_deployment=AZURE_OPENAI_CHAT_DEPLOYMENT,
        openai_api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        temperature=0.1
    )
    _ = llm.invoke("hello")
    print("✅ Successfully initialized Azure OpenAI Chat Model.")
except Exception as e:
    print(f"❌ CRITICAL ERROR initializing Azure OpenAI Chat Model: {e}")
    llm = None

# --- Initialize Vector Store Client (Azure AI Search) ---
try:
    AZURE_AI_SEARCH_ENDPOINT = os.getenv("AZURE_AI_SEARCH_ENDPOINT")
    AZURE_AI_SEARCH_KEY = os.getenv("AZURE_AI_SEARCH_KEY")
    AZURE_AI_SEARCH_INDEX_NAME = os.getenv("AZURE_AI_SEARCH_INDEX_NAME")
    if all([AZURE_AI_SEARCH_ENDPOINT, AZURE_AI_SEARCH_KEY, AZURE_AI_SEARCH_INDEX_NAME, embeddings_client]):
        print(f"Initializing Azure AI Search vector store for index: {AZURE_AI_SEARCH_INDEX_NAME}")
        vector_store_for_manual_rag = AzureSearch(
            azure_search_endpoint=AZURE_AI_SEARCH_ENDPOINT,
            azure_search_key=AZURE_AI_SEARCH_KEY,
            index_name=AZURE_AI_SEARCH_INDEX_NAME,
            embedding_function=embeddings_client.embed_query,
            vector_field_name="content_vector"
        )
        print("✅ Global vector store initialized successfully.")
    else:
        print("⚠️ Could not initialize global vector store due to missing configuration or failed embedding client init.")
except Exception as e:
    print(f"❌ Error initializing global vector store: {e}")
    vector_store_for_manual_rag = None

# --- DEFINITIVE PROMPT TEMPLATE (Fixes "Bunched Text") ---
RFP_PROMPT_TEMPLATE = """
You are an expert RFP and tender document analyst for Think Tank Software Solutions. 
Your primary goal is to provide clear, concise, and professionally formatted answers using Markdown.

---
**EXAMPLE**

**CONTEXT:**
The deadline for all proposal submissions is May 1st, 2024 at 5:00 PM. The solution must support at least 50 concurrent users. Bidders must have a Level 2 B-BBEE certification.

**QUESTION:**
What are the key requirements and deadlines?

**ANALYST'S RESPONSE:**
### **Key Requirements & Deadlines**

Based on the provided documents, here are the critical details:

*   **Submission Deadline:** The final proposal must be submitted no later than **May 1st, 2024 at 5:00 PM**.
*   **User Scale:** The proposed solution is required to support a minimum of **50 concurrent users**.
*   **Compliance:** A valid **Level 2 B-BBEE certification** is a mandatory requirement for all bidders.
---

**YOUR TASK**

**CONTEXT:**
{context}

**QUESTION:** {question}

**ANALYST'S RESPONSE (Use Markdown formatting similar to the example):**
"""
RFP_PROMPT = PromptTemplate(template=RFP_PROMPT_TEMPLATE, input_variables=["context", "question"])

# --- THE COMPLETE, FIXED RAG FUNCTION ---
def perform_manual_rag_query(user_query: str, vector_store_obj, llm_client_obj, prompt_template_obj: PromptTemplate, target_document_name: str = None):
    if not all([vector_store_obj, embeddings_client, llm_client_obj]):
        error_msg = "Error: A required backend component (vector store, embeddings, or LLM) is not initialized."
        print(f"BACKEND ERROR: {error_msg}")
        return {"answer": error_msg, "sources_for_ui": []}

    try:
        # Check the TYPE of the vector store to decide how to query it.
        if isinstance(vector_store_obj, AzureSearch):
            print(f"DEBUG: Querying Azure AI Search for: '{user_query}'")
            search_filters = None
            if target_document_name and target_document_name != "All Indexed Documents": 
                search_filters = f"source_document eq '{target_document_name}'"
            print(f"DEBUG: Applying filter: '{search_filters}'")
            retrieved_docs = vector_store_obj.similarity_search(query=user_query, k=3, filters=search_filters)
        else: # Assumes it's a temporary Chroma store from an upload
            print(f"DEBUG: Querying temporary in-memory Chroma DB for: '{user_query}'")
            retrieved_docs = vector_store_obj.similarity_search(query=user_query, k=3)
        
        if not retrieved_docs:
            return {"answer": "No relevant information found in the selected documents for your query.", "sources_for_ui": []}

        print(f"DEBUG: Retrieved {len(retrieved_docs)} documents for context.")
        context_parts = [doc.page_content for doc in retrieved_docs]
        combined_context = "\n\n---\n\n".join(context_parts)
        
        formatted_prompt_str = prompt_template_obj.format(context=combined_context, question=user_query)
        
        print("DEBUG: Sending formatted prompt to LLM.")
        response_message_obj = llm_client_obj.invoke(formatted_prompt_str)
        answer = response_message_obj.content if hasattr(response_message_obj, 'content') else str(response_message_obj)
        print("DEBUG: LLM invocation complete.")
        
        source_info_for_display = [{"source_document": doc.metadata.get('source_document', 'Uploaded Document'), "content_snippet": doc.page_content} for doc in retrieved_docs]
        return {"answer": answer, "sources_for_ui": source_info_for_display}

    except Exception as e:
        print(f"Error in perform_manual_rag_query: {e}")
        traceback.print_exc()
        return {"answer": f"An error occurred in the backend while processing your RAG query: {str(e)}", "sources_for_ui": []}

# --- Indexing and other utility functions from your original file ---
# (Assuming these are correct and complete in your version)

print("\n--- RAG Core Turbo Backend Initialization Complete ---")