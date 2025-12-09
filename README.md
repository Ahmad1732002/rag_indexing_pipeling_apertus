# ETH Zurich Web Archive Processing Pipeline

This repository provides tools to process ETH Zurich web archive files (WARC format) and index them into Elasticsearch for semantic search and retrieval-augmented generation (RAG).

## Features

- Extract HTML and PDF files from WARC archives
- Combine domain-specific HTML files by timestamp
- Convert HTML to Markdown format
- Index documents to Elasticsearch with embeddings
- Query indexed documents using semantic search or RAG

## Prerequisites

- [Mamba](https://mamba.readthedocs.io/) or [Conda](https://docs.conda.io/)
- [Ollama](https://ollama.ai/) for embedding models
- Access to an Elasticsearch instance

## Installation

### 1. Clone this repository

### 2. Create the environment

Using mamba (recommended for faster installation):

```bash
mamba env create -f env.yml
mamba activate rag
```

Or using conda:

```bash
conda env create -f env.yml
conda activate rag
```

### 3. Install Ollama and pull the embedding model

Install Ollama from [https://ollama.ai/](https://ollama.ai/)

Then pull the required embedding model:

```bash
ollama pull all-minilm
```

(For Later: Pull LLM for generation)

### 4. Configure environment variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit [.env](.env) and add your Elasticsearch credentials:

```bash
ELASTIC_USERNAME=your_elasticsearch_username
ELASTIC_PASSWORD=your_elasticsearch_password
ES_URL=https://es.swissai.cscs.ch
EMBEDDING_MODEL=all-minilm
INDEX_NAME=ethz_webarchive
```

**Required variables:**

- `ELASTIC_USERNAME`: Your Elasticsearch username
- `ELASTIC_PASSWORD`: Your Elasticsearch password

**Optional variables (defaults provided):**

- `ES_URL`: Elasticsearch URL (default: https://es.swissai.cscs.ch)
- `EMBEDDING_MODEL`: Ollama embedding model name (default: all-minilm)
- `INDEX_NAME`: Elasticsearch index name (default: ethz_webarchive)

## Usage

### Indexing Pipeline

To process WARC files and index them to Elasticsearch:

```bash
python run_indexing_pipeline.py
```

This script will:

1. Extract HTML and PDF files from WARC archives
2. Combine HTML files by domain and timestamp
3. Convert HTML to Markdown
4. Generate embeddings using Ollama
5. Index documents to Elasticsearch

The pipeline processes files from `./data/ethz_websites_2022-2025_examples/` and outputs to `./output/`.

### Querying Indexed Documents

```bash
python run_query.py
```

## Running on CSCS Cluster (No GPU)

The CSCS cluster requires that your environment be packaged into a SquashFS container (.sqsh) using Podman and Enroot. This section outlines the build and deployment process for running your job via sbatch.

### Step 1: Build the Container Image

This step is performed once from a compute node to create the container file (ethz_cpu_rag.sqsh).

**a. Save the Dockerfile:** Ensure the Dockerfile (containing your Python dependencies) is saved in your project root.

**b. Get a Compute Node:** Request an interactive shell session.

```bash
srun --nodes=1 --time=01:00:00 --partition=normal --account=large-sc-2 --container-writable --pty bash
```

**c. Navigate to Project:** Go to the directory containing your Dockerfile.

```bash
cd /iopsstor/scratch/cscs/$USER/path/to/project/
```

**d. Build the Image (Podman):** This reads the Dockerfile and creates a local image.

```bash
podman build -t ethz_cpu_rag:v1 .
```

**e. Convert to SquashFS (Enroot):** This creates the final, runnable container file (.sqsh).

```bash
enroot import -o ethz_cpu_rag.sqsh podman://ethz_cpu_rag:v1
```

**f. Exit:**

```bash
exit
```

### Step 2: Create the Enroot TOML Configuration

Create a configuration file to tell the cluster environment how to run your .sqsh container. This file must be placed in your dedicated Enroot configuration directory.

Create the file `~/.edf/rag_env.toml` (using the path to your new container):

```toml
# ~/.edf/rag_env.toml
image = "/iopsstor/scratch/cscs/<your_username>/path/to/project/ethz_cpu_rag.sqsh"
mounts = [
    # Mount your scratch directory so the container can access inputs/outputs
    "/iopsstor/scratch/cscs/<your_username>:/iopsstor/scratch/cscs/<your_username>"
]
writable = true
```

**Note:** Replace `<your_username>` and the project path with your actual details.

### Step 3: Run the Indexing Job

Submit your sbatch script ([run_pipeline.sbatch](run_pipeline.sbatch)), passing the container configuration name and the required input paths.

```bash
sbatch run_pipeline.sbatch \
    --container-name=rag_env \
    /iopsstor/scratch/cscs/$USER/data/warc_files \
    /iopsstor/scratch/cscs/$USER/config/topics.xlsx
```

## Project Structure

```
ethz_webarchive/
├── data/                           # Input WARC files
├── output/                         # Processing outputs
│   ├── html_raw/                  # Extracted HTML files
│   ├── pdf_raw/                   # Extracted PDF files
│   ├── html_combined/             # Combined HTML by domain
│   ├── markdown/                  # Converted Markdown files
│   └── mappings/                  # Domain and timestamp mappings
├── prep_warc_files.py             # WARC extraction utilities
├── combine_domains.py             # Domain combination logic
├── html_combined_to_markdown.py   # HTML to Markdown conversion
├── index_to_elasticsearch.py      # Elasticsearch indexing
├── query_elasticsearch.py         # Query utilities
├── run_indexing_pipeline.py       # Main pipeline script
├── env.yml                        # Mamba/Conda environment
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment variables template
└── README.md                      # This file
```

## Troubleshooting

### Ollama connection issues

Make sure Ollama is running:

```bash
ollama serve
```

Verify the model is available:

```bash
ollama list
```

### Elasticsearch connection issues

Check your credentials in [.env](.env) and verify you can reach the Elasticsearch server:

```bash
curl -u username:password https://es.swissai.cscs.ch
```

### Memory issues during indexing

If you encounter memory issues, you can reduce the batch size in [index_to_elasticsearch.py](index_to_elasticsearch.py#L406) (line 406).

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is part of ETH Zurich's web archiving efforts.

# Credit

Inspired by [this repo](https://github.com/rashitig/ethz_webarchive)
