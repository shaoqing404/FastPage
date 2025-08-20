<div align="center">
  <a href="https://vectify.ai/pageindex" target="_blank">
    <img width="4500" height="1500" alt="image" src="https://github.com/user-attachments/assets/46201e72-675b-43bc-bfbd-081cc6b65a1d" />
  </a>

</div>

# [📄 PageIndex](https://pageindex.ai)

Are you frustrated with vector database retrieval accuracy for long professional documents? Traditional vector-based RAG relies on semantic *similarity* rather than true *relevance*. But **similarity ≠ relevance** — what we truly need in retrieval is **relevance**, and that requires **reasoning**. When working with professional documents that demand domain expertise and multi-step reasoning, similarity search often falls short.

**[Reasoning-based RAG](https://pageindex.ai)** 🧠 offers a better alternative: enabling LLMs to **think** and **reason** their way to the most relevant document sections. Inspired by AlphaGo, we use **tree search** to perform structured document retrieval, which simulates how **human experts** navigate and extract knowledge from complex documents.

**[PageIndex](https://vectify.ai/pageindex)** is a *document indexing system* that builds **search tree structures** from long documents, making them ready for **reasoning-based RAG**.  It has been used to develop a RAG system that achieved 98.7% accuracy on [FinanceBench](https://vectify.ai/blog/Mafin2.5), demonstrating state-of-the-art performance in document analysis.

Try [Reasoning-based RAG with PageIndex](https://pageindex.ai) — no vector DB required. Say goodbye to *"vibe retrieval"* 👋
- No *Vector DB*, No *Chunking*, No *Top-K* selection
- Human-like Retrieval, Higher Accuracy, Better Transparency
  
#### 🚀 Deployment Options  
- 🛠️ Self-host — run it yourself with this open-source repo
- ☁️ **[Cloud Service](https://dash.pageindex.ai/)** — try instantly with our 🖥️ [Dashboard](https://dash.pageindex.ai/) or 🔌 [API](https://docs.pageindex.ai/quickstart), no setup required

---

# **⭐ What is PageIndex**

PageIndex can transform lengthy PDF documents into a semantic **tree structure**, similar to a *"table of contents"* but optimized for use with Large Language Models (LLMs).
It's ideal for: financial reports, regulatory filings, academic textbooks, legal or technical manuals, and any document that exceeds LLM context limits.

### ✅ Key Features
    
- **Hierarchical Tree Structure**  
  Enables LLMs to traverse documents logically — like an intelligent, LLM-optimized table of contents.

- **Chunk-Free Segmentation**  
  No arbitrary chunking. Nodes follow the natural structure of the document.

- **Precise Page Referencing**  
  Every node contains its summary and start/end page physical index, allowing pinpoint retrieval.

- **Scales to Massive Documents**  
  Designed to handle hundreds or even thousands of pages with ease.

### 📦 PageIndex Format

Here is an example output. See more [example documents](https://github.com/VectifyAI/PageIndex/tree/main/docs) and [generated trees](https://github.com/VectifyAI/PageIndex/tree/main/results).

```
...
{
  "title": "Financial Stability",
  "node_id": "0006",
  "start_index": 21,
  "end_index": 22,
  "summary": "The Federal Reserve ...",
  "nodes": [
    {
      "title": "Monitoring Financial Vulnerabilities",
      "node_id": "0007",
      "start_index": 22,
      "end_index": 28,
      "summary": "The Federal Reserve's monitoring ..."
    },
    {
      "title": "Domestic and International Cooperation and Coordination",
      "node_id": "0008",
      "start_index": 28,
      "end_index": 31,
      "summary": "In 2023, the Federal Reserve collaborated ..."
    }
  ]
}
...
```

---

# 🚀 Package Usage

Follow these steps to generate a PageIndex tree from a PDF document.

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Set your OpenAI API key

Create a `.env` file in the root directory and add your API key:

```bash
CHATGPT_API_KEY=your_openai_key_here
```

### 3. Run PageIndex on your PDF

```bash
python3 run_pageindex.py --pdf_path /path/to/your/document.pdf
```
You can customize the processing with additional optional arguments:

```
--model                 OpenAI model to use (default: gpt-4o-2024-11-20)
--toc-check-pages       Pages to check for table of contents (default: 20)
--max-pages-per-node    Max pages per node (default: 10)
--max-tokens-per-node   Max tokens per node (default: 20000)
--if-add-node-id        Add node ID (yes/no, default: yes)
--if-add-node-summary   Add node summary (yes/no, default: no)
--if-add-doc-description Add doc description (yes/no, default: yes)
```

---

# ☁️ Cloud API & Platform (Beta)

Don't want to host it yourself? Try our [hosted API](https://pageindex.vectify.ai/) for PageIndex. The hosted service leverages our custom OCR model for more accurate PDF recognition, delivering better tree structures for complex documents. Ideal for rapid prototyping, production environments, and documents requiring advanced OCR.

You can also upload PDFs from your browser and explore results visually with our [Dashboard](https://pageindex.vectify.ai/overview) — no coding needed.

Leave your email in [this form](https://ii2abc2jejf.typeform.com/to/meB40zV0) to receive 1,000 pages for free.

---

### PageIndex OCR (Updates On 2025/08/07)
This repo is designed for generating PageIndex tree structure with text input, but many real-world use cases involve PDFs that require OCR to convert them into Markdown. However, extracting high-quality text from PDF documents remains a non-trivial challenge. Most OCR tools only extract page-level content, losing the broader document context and hierarchy.
 
To address this, we introduced PageIndex OCR — the first OCR system designed to preserve the global structure of documents. PageIndex OCR significantly outperforms other leading OCR tools, such as those from Mistral and Contextual AI, in recognizing true hierarchy and semantic relationships across document pages.

- Experience next-level OCR quality with PageIndex OCR at our [Dashboard](https://dash.pageindex.ai).
- Integrate seamlessly PageIndex OCR into your stack via our [API](https://docs.pageindex.ai/quickstart).

<p align="center">
  <img src="https://github.com/user-attachments/assets/eb35d8ae-865c-4e60-a33b-ebbd00c41732" width="90%">
</p>

---

# 📈 Case Study: Mafin 2.5 on FinanceBench

[Mafin 2.5](https://vectify.ai/mafin) is a state-of-the-art reasoning-based RAG model designed specifically for financial document analysis. Powered by **PageIndex**, it achieved a market-leading [**98.7% accuracy**](https://vectify.ai/blog/Mafin2.5) on the [FinanceBench](https://arxiv.org/abs/2311.11944) benchmark — significantly outperforming traditional vector-based RAG systems.

PageIndex's hierarchical indexing enabled precise navigation and extraction of relevant content from complex financial reports, such as SEC filings and earnings disclosures.

👉 See the full [benchmark results](https://github.com/VectifyAI/Mafin2.5-FinanceBench) and our [blog post](https://vectify.ai/blog/Mafin2.5) for detailed comparisons and performance metrics.

<div align="center">
  <a href="https://github.com/VectifyAI/Mafin2.5-FinanceBench">
    <img src="https://github.com/user-attachments/assets/571aa074-d803-43c7-80c4-a04254b782a3" width="90%">
  </a>
</div>

---

# 🧠 Reasoning-Based RAG with PageIndex

Use PageIndex to build **reasoning-based retrieval systems** without relying on semantic similarity. Great for domain-specific tasks where nuance matters (see **[more examples](https://pageindex.vectify.ai/examples/rag)**).

### 🔖 Preprocessing Workflow Example
1. Process documents using PageIndex to generate tree structures.
2. Store the tree structures and their corresponding document IDs in a database table.
3. Store the contents of each node in a separate table, indexed by node ID and tree ID.

### 🔖 Reasoning-Based RAG Framework Example
1. Query Preprocessing:
    - Analyze the query to identify the required knowledge
2. Document Selection: 
    - Search for relevant documents and their IDs
    - Fetch the corresponding tree structures from the database
3. Node Selection:
    - Search through tree structures to identify relevant nodes
4. LLM Generation:
    - Fetch the corresponding contents of the selected nodes from the database
    - Format and extract the relevant information
    - Send the assembled context along with the original query to the LLM
    - Generate contextually informed responses


### 🔖 Example Prompt for Node Selection

```python
prompt = f"""
You are given a question and a tree structure of a document.
You need to find all nodes that are likely to contain the answer.

Question: {question}

Document tree structure: {structure}

Reply in the following JSON format:
{{
    "thinking": <reasoning about where to look>,
    "node_list": [node_id1, node_id2, ...]
}}
"""
```

---

# 📬 Contact Us

Need customized support for your documents or reasoning-based RAG system?

:loudspeaker: [Join our Discord](https://discord.com/invite/nnyyEdT2RG)

:envelope: [Leave us a message](https://ii2abc2jejf.typeform.com/to/meB40zV0)

Built by <a href="https://vectify.ai" target="_blank">Vectify AI</a>.
