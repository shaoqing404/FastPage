# PageIndex



### **Document Index System for Reasoning-Based RAG**
Are you frustrated with vector database retrieval accuracy for long professional documents? You need a reasoning-based native index for your RAG system.

Traditional vector-based retrieval relies heavily on semantic similarity. However, when working with professional documents that require domain expertise and multi-step reasoning, similarity search often falls short.

**Reasoning-Based RAG** offers a better alternative: enabling LLMs to *think* and *reason* their way to the most relevant document sections. Inspired by **AlphaGo**, we leverage **tree search** to perform structured document retrieval.

**[PageIndex](https://vectify.ai/pageindex)** is an indexing system that builds search trees from long documents, making them ready for reasoning-based RAG.

Built by [Vectify AI](https://vectify.ai/pageindex)

## ☁️ Hosted API (Beta)
Please try our [hosted API for PageIndex](https://pageindex.vectify.ai/).
The hosted version uses our custom OCR model to recognize PDFs more accurately, providing a better tree structure for complex documents.
Leave your email in [this form](https://ii2abc2jejf.typeform.com/to/meB40zV0) to receive 1,000 pages for free.

---

## 🔍 What is PageIndex?

**PageIndex** transforms lengthy PDF documents into a semantic **tree structure**, similar to a "table of contents" but optimized for use with Large Language Models (LLMs).
It’s ideal for: financial reports, regulatory filings, academic textbooks, legal or technical manuals or any document that exceeds LLM context limits.

### ✅ Key Features

- **Scales to Massive Documents**  
  Designed to handle hundreds or even thousands of pages with ease.
    
- **Hierarchical Tree Structure**  
  Enables LLMs to traverse documents logically—like an intelligent, LLM-optimized table of contents.

- **Precise Page Referencing**  
  Every node contains its summary and start/end page physical index, allowing pinpoint retrieval.

- **Chunk-Free Segmentation**  
  No arbitrary chunking. Nodes follow the natural structure of the document.

---

## 📦 PageIndex Format

Here is an example output. See more [example documents](https://github.com/VectifyAI/PageIndex/tree/main/docs) and [generated trees](https://github.com/VectifyAI/PageIndex/tree/main/results).

```json
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

```
## 🧠 Reasoning-Based RAG with PageIndex

Use PageIndex to build **reasoning-based retrieval systems** without relying on semantic similarity. Great for domain-specific tasks where nuance matters.

### 🛠️ Example Prompt

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

## 🚀 Usage

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

```bash
--model                 OpenAI model to use (default: gpt-4o-2024-11-20)
--toc-check-pages       Pages to check for table of contents (default: 20)
--max-pages-per-node    Max pages per node (default: 10)
--max-tokens-per-node   Max tokens per node (default: 20000)
--if-add-node-id        Add node ID (yes/no, default: yes)
--if-add-node-summary   Add node summary (yes/no, default: no)
--if-add-doc-description Add doc description (yes/no, default: yes)
```


## 🛤 Roadmap

- [ ]  Document-level retrieval
- [ ]  Technical report on PageIndex design
- [ ]  Efficient tree search algorithms for large documents
- [ ]  Integration with vector-based semantic retrieval

## 📈 Case Study: Mafin 2.5

[Mafin 2.5](https://vectify.ai/blog/Mafin2.5) is a state-of-the-art reasoning-based RAG model designed specifically for financial document analysis. Built on top of **PageIndex**, it achieved an impressive **98.7% accuracy** on the [FinanceBench](https://github.com/VectifyAI/Mafin2.5-FinanceBench) benchmark—significantly outperforming traditional vector-based RAG systems.

PageIndex’s hierarchical indexing enabled precise navigation and extraction of relevant content from complex financial reports, such as SEC filings and earnings disclosures.

👉 See full [benchmark results](https://github.com/VectifyAI/Mafin2.5-FinanceBench) for detailed comparisons and performance metrics.

## 🚧 Notice

This project is in its early beta development, and all progress will remain open and transparent.  
Due to the non-deterministic nature of large language models (LLMs) and the diverse structures of PDF documents, you may encounter bugs or instability during usage.

We welcome you to raise issues, reach out with questions, or contribute directly to the project.  
Together, let's push forward the revolution of reasoning-based RAG systems.



## 📬 Contact Us

Need customized support for your documents or reasoning-based RAG system?

:loudspeaker: [Join our Discord](https://discord.com/invite/nnyyEdT2RG)

:envelope: [Leave us a message](https://ii2abc2jejf.typeform.com/to/meB40zV0)
