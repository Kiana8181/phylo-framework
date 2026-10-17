# clonotype

## Running the Pipeline

Follow the steps below to run the clonotype pipeline.

### 1. Prepare the Dataset

You will need an **AIRR sequence dataset** (for example: `I1_mobille`).

* Inside the `data/` directory, create a new folder named after your dataset:

  ```
  data/<dataset_name>/
  ```

* Place your AIRR `.tsv` file inside that folder.

Example:

```
data/
└── I1_mobille/
    └── vquest_airr.tsv
```

---

### 2. Set Up the Environment

Install the required dependencies:

```bash
pip install -r requirements.txt
```

We recommend creating a fresh Python environment with **Python 3.12**.

Using Conda:

```bash
conda config --add channels bioconda
conda config --add channels conda-forge
conda config --set channel_priority strict

conda create -n clonotype python=3.12
conda activate clonotype

pip install -r requirements.txt
conda install bioconda::muscle
```

---

### 3. Run the Pipeline

Execute the pipeline with:

```bash
python main_pipeline.py <dataset_name> ./data/<dataset_name>/<tsv_file>
```

Example:

```bash
python main_pipeline.py I1_mobille ./data/I1_mobille/vquest_airr.tsv
```