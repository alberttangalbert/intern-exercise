# intern-exercise

A Python-based pipeline for extracting, classifying, and analyzing clinical trial drug mechanisms using large language models and the MeSH (Medical Subject Headings) taxonomy.

## Overview

This pipeline processes clinical trial data to:
1. **Extract and map drug interventions** from trial metadata
2. **Classify drugs** as Innovative, Generic, or Biosimilar
3. **Identify mechanisms of action (MOA)** using PubMed literature and MeSH terms
4. **Categorize drugs** into 9 high-level pharmacologic super-groups

## Project Structure
```
.
├── run.ipynb                          # Main execution notebook
├── data/
│   └── raw_trials.csv                 # Input: raw clinical trial data
├── cache/
│   ├── data_preprocess/               # Preprocessed trial data with hashes
│   ├── task_1/                        # Drug role extraction & mapping
│   ├── task_2/                        # Innovation status classification
│   └── task_3/                        # MOA identification & MeSH mapping
├── output/
│   └── trial_results_table.csv        # Final human-readable results
├── services/
│   └── openai_wrapper.py              # LLM API wrapper
├── requirements.txt                   # Python dependencies
└── .env.example                       # Environment variable template
```

## Setup

### 1. Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
```bash
cp .env.example .env
```

Edit `.env` and fill in the required variables:
```bash
# OpenAI API Configuration
OPENAI_API_KEY=your_openai_api_key_here

# NCBI E-utilities Configuration (for PubMed access)
NCBI_API_KEY=your_ncbi_api_key_here
NCBI_EMAIL=your_email@example.com
```

**Getting API Keys**:
- **OpenAI**: Sign up at https://platform.openai.com/api-keys
- **NCBI API Key**: Register at https://www.ncbi.nlm.nih.gov/account/ (optional but recommended for higher rate limits)

### 4. Prepare Input Data

**Option A: Download Pre-Generated Cache (Recommended)**

To skip the full pipeline execution (~2-3 hours) and use pre-computed results:

1. **Download the cache archive**:
   - [Download cache.zip from Google Drive](https://drive.google.com/file/d/1jcyAzXS4fwVy-LMS9c7DFi3S-zFem7Ye/view?usp=sharing)
   - Extract to the project root directory (this will create the `cache/` folder structure)

2. **Download the input data**:
   - [Download raw_trials.csv from Google Drive](https://drive.google.com/file/d/1EGONvQsQ0yU7eo0A9ifgQySVBU5VogaL/view?usp=sharing)
   - Create a `data/` folder in the project root
   - Place `raw_trials.csv` inside the `data/` folder

With the pre-generated cache, you can skip directly to exploring results or run individual pipeline stages.

**Option B: Run Full Pipeline from Scratch**

1. **Download the input data**:
   - [Download raw_trials.csv from Google Drive](https://drive.google.com/file/d/1EGONvQsQ0yU7eo0A9ifgQySVBU5VogaL/view?usp=sharing)
   - Create a `data/` folder in the project root
   - Place `raw_trials.csv` inside the `data/` folder

2. The input file should contain the following required columns:
   - `title`
   - `start_date`
   - `phase`
   - Additional metadata columns used for extraction (see notebook for full list)

3. Ensure your OpenAI API key is configured (see step 3 above)

## Requirements

### Python Dependencies
```
pandas>=2.0.0
requests>=2.31.0
openai>=1.0.0
python-dotenv>=1.0.0
```

### External APIs
- **OpenAI Responses API** (GPT-5/GPT-5-mini/GPT-5-nano) via `services.openai_wrapper`
- **NCBI E-utilities** (PubMed search) - requires `NCBI_API_KEY` and `NCBI_EMAIL` environment variables

## Pipeline Stages

### Stage 0: Data Preprocessing
- Generates deterministic `trial_hash` IDs (MD5 of title + start_date + phase)
- **Output**: `cache/data_preprocess/raw_trials_with_hash.csv`

### Stage 1: Drug Role Extraction (Task 1)
**Purpose**: Identify all drugs in each trial and classify their roles

**Process**:
1. LLM extracts drugs from trial metadata fields
2. Canonicalizes drug names (removes manufacturer qualifiers)
3. Assigns roles: Investigational Product, Placebo, Active Comparator, Standard of Care
4. Maps drugs to TrialTrove/BioMedTracker IDs when available
5. Creates deterministic `did_*` identifiers for each unique drug

**Key Outputs**:
- `cache/task_1/trial_drug_roles/{trial_hash}.json` - per-trial mappings
- `cache/task_1/trial_product_breakdown.csv` - wide-format trial-level table
- `cache/task_1/product_id_master_by_did.json` - drug master index (keyed by `did`)

**Cost**: $4.40 for 184 trials ($0.024/trial)

### Stage 2: Innovation Classification (Task 2)
**Purpose**: Classify investigational drugs as Innovative, Generic, or Biosimilar

**Classification Criteria**:
- **Innovative**: Novel molecular entity, new mechanism, or sponsor's lead product
- **Generic**: Small-molecule copy of approved branded drug
- **Biosimilar**: Biologic highly similar to approved reference product (demonstrated via equivalence/non-inferiority)

**Key Outputs**:
- `cache/task_2/trial_investigational_drugs_classifications.csv`

**Cost**: $1.88 for 179 trials with investigational products ($0.011/trial)

### Stage 3: Mechanism of Action Identification (Task 3)

#### 3A: PubMed Literature Search
**Purpose**: Find scientific evidence for drug mechanisms

**Process**:
1. For each drug (by `did`), search PubMed using:
   - Mechanism strings (from TrialTrove/BioMedTracker metadata)
   - Molecular targets
   - LLM-refined mechanism terms (if initial search fails)
2. Fetch article metadata: title, abstract, MeSH terms, substances
3. Store top 5 articles per mechanism term + 10 per target term

**Key Outputs**:
- `cache/task_3/investigational_drug_moa_pubmed_search/{did}.json`
- `cache/task_3/investigational_drug_moa_pubmed_index.json`

#### 3B: MeSH Term Selection
**Purpose**: Choose single canonical MeSH term representing each drug's MOA

**Process**:
1. Extract candidate MeSH terms from PubMed results
2. LLM selects most mechanistically specific term (or `[none]` if unsuitable)
3. Strict validation: chosen term must exist in candidate list

**Key Outputs**:
- `cache/task_3/investigational_drug_moa_chosen/{did}.json`
- `cache/task_3/investigational_drug_moa_chosen_master.json`

#### 3C: MeSH Tree Number Mapping
**Purpose**: Map MeSH terms to hierarchical tree numbers

**Data Sources**:
- `desc2025.xml` - MeSH descriptor records (downloaded from NLM)
- `supp2025.xml` - Supplementary concept records

**Process**:
1. Build in-memory index: `normalized_term → {mesh_id, tree_numbers, scope_note}`
2. For each trial, map chosen MeSH terms to tree numbers
3. Select "primary" tree number using pharmacologic heuristic (prefers D12/D27/D02 branches)

**Key Outputs**:
- `cache/task_3/trial_mechanism_mesh_mapping.csv`

#### 3D: MOA Super-Group Classification
**Purpose**: Categorize mechanisms into 9 high-level buckets

**Categories**:
1. `cytokine_hormone_receptor_modulators` - EPO-R, TPO-R, IL-2R agonists
2. `immune_checkpoint_immune_modulation` - PD-1/PD-L1, TNF inhibitors
3. `targeted_pathway_inhibitors` - HER2, VEGF, JAK/mTOR inhibitors
4. `classical_cytotoxic_chemotherapy` - Alkylators, antimetabolites, tubulin modulators
5. `biologic_antibodies_biologics` - Monoclonal/bispecific antibodies, CAR-T
6. `small_molecule_immunomod_antiinflammatory` - PDE4i, calcineurin inhibitors, glucocorticoids
7. `metabolic_pathway_modulators` - DHFR, thymidylate synthase, HIF-PH inhibitors
8. `vaccines_immune_biologics` - Therapeutic vaccines, fusion proteins
9. `supportive_adjunctive_agents` - Supportive care, rescue agents

**Heuristic**:
- Text pattern matching on MeSH term + tree number branch
- Pharmacologically-informed priority rules
- Deterministic (no LLM calls)

**Key Outputs**:
- `cache/task_3/trial_mechanism_super_group_mapping.csv` - (mesh_term, tree_number) → super_group
- `cache/task_3/trial_mechanism_with_super_groups.csv` - trial-level table with super-groups
- `cache/task_3/trial_super_group_distribution.csv` - frequency distribution

## Final Output

**File**: `output/trial_results_table.csv`

**Columns**:
- `trial_title` - Human-readable trial title
- `drug_name` - Cleaned drug name(s), joined by `+` for combinations
- `moa` - Mechanism of action (MeSH-based, normalized)
- `innovation_generic_biosimilar` - Innovation status (Innovative/Generic/Biosimilar)
- `category` - MOA super-group

**Cleaning Applied**:
- Parenthetical text removed from drug names
- MOA strings normalized: drops text after `/`, removes `*`, preserves `+` separators
- Innovation flags canonicalized to title-case

## Execution
```bash
# Activate virtual environment
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Run entire pipeline
jupyter notebook run.ipynb
```

**Expected Runtime**: ~2-3 hours (depending on API rate limits)

**Total LLM Cost**: ~$6.28 for 184 trials
- Task 1 (drug extraction): $4.40
- Task 2 (innovation classification): $1.88

## OpenAI Wrapper Implementation

The pipeline uses a custom `OpenAIWrapper` class (`services/openai_wrapper.py`) that interfaces with the OpenAI Responses API and provides automatic cost tracking.

### Supported Models
- **gpt-5**: $1.25/1M input tokens, $10.00/1M output tokens
- **gpt-5-mini**: $0.25/1M input tokens, $2.00/1M output tokens
- **gpt-5-nano**: $0.05/1M input tokens, $0.40/1M output tokens

### Key Features
1. **Automatic Cost Calculation**: Tracks token usage and computes USD cost per request
2. **Reasoning Token Billing**: Correctly accounts for reasoning tokens in output billing
3. **Web Search Tool Costs**: Adds $0.01 flat fee per web search tool call
4. **Response Format Support**: Handles both text and JSON response formats
5. **Error Handling**: Graceful failure with detailed error logging

### Usage Example
```python
from services.openai_wrapper import OpenAIWrapper

wrapper = OpenAIWrapper()
result = wrapper.query(
    prompt="Your prompt here",
    model="gpt-5-mini",
    tools=[{"type": "web_search"}],  # Optional
    response_format="json_object"    # or "text"
)

print(result["text_response"])  # Assistant's response text
print(f"Cost: ${result['cost']}")  # Request cost in USD
```

### Cost Breakdown
The wrapper returns a dictionary with:
- `text_response`: The assistant's text output
- `raw_response`: Full API response object
- `cost`: Total cost in USD (includes input tokens, output tokens, reasoning tokens, and web search fees)

## Key Design Decisions

### 1. Deterministic Identifiers
- trial hashes
   - `tid_*` = MD5(title + start_date + phase) for stable trial IDs
- drug hashes
   - `did_*` = MD5(composite key) for unique drug IDs across the dataset

### 2. LLM Prompt Engineering
- **Strict output format validation**: JSON schema enforcement
- **Coverage checks**: Verify all drugs classified before saving results
- **Fallback mechanisms**: LLM-refined search terms if initial PubMed queries fail

### 3. MeSH Tree Number Selection
- **Primary tree heuristic**: Prefers pharmacologically-relevant branches (D12 > D27 > D02)
- **Depth preference**: Chooses more specific (deeper) terms within priority branches
- **Fallback chain**: Mechanism-based MeSH → Drug-based MeSH → empty

## Limitations & Known Issues

### Discovered Mapping Errors
Two drugs were incorrectly mapped to wrong TrialTrove IDs:
1. **"601"** (AER-601, GLP-1 agonist) → wrongly mapped to anti-VEGF ophthalmic biologic
2. **"Inetetamab"** (HER2 mAb) → wrongly mapped to inotuzumab ozogamicin (CD22 ADC)

**Root Cause**: Ambiguous short names + insufficient context in initial name resolution

### Missing Data
- **SSS-24**: Mechanism of action not disclosed in trial or public sources (1 trial affected)
- **5 trials** have no investigational products (treatment strategy/regimen studies only)

### Citation Coverage
- 127/129 drugs have PubMed-based MOA evidence
- 2 drugs could not be matched to MeSH terms (returned `[none]`)