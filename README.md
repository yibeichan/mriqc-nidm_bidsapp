# MRIQC-NIDM Converter

A BIDS App that converts MRIQC output to NIDM format.

## Repository Structure

```
.
├── README.md                 # This file
├── LICENSE                   # License file
├── Dockerfile               # Docker definition file
├── Singularity              # Apptainer definition file
├── setup.py                 # Package setup
├── requirements.txt         # Python dependencies
├── src/
│   └── mriqc_nidm/
│       ├── __init__.py
│       ├── run.py                    # Main entry point
│       ├── csv_to_nidm.py           # CSV to NIDM conversion
│       ├── json_to_csv.py           # JSON to CSV conversion
│       ├── mriqc_wrapper.py         # MRIQC execution wrapper
│       ├── nidm_handler.py         # NIDM file handling
│       └── data/                   # Data files
│           ├── mriqc_dictionary_v1.csv
│           └── mriqc_software_metadata.csv
├── tests/                   # Test suite
├── docs/                    # Documentation
│   └── OUTPUT_STRUCTURE.md
└── scripts/                 # Utility scripts
```

## Installation

### Using Apptainer

1. Build the container:
```bash
apptainer build mriqc-nidm.sif mriqc-nidm.def
```

2. Run the container:
```bash
apptainer run mriqc-nidm.sif /path/to/mriqc/output /path/to/output participant
```

### Using Docker

1. Build the container:
```bash
docker build -t mriqc-nidm .
```

2. Run the container:
```bash
docker run -v /path/to/mriqc/output:/data -v /path/to/output:/out mriqc-nidm /data /out participant
```

## Usage

The app runs MRIQC quality control and converts the output to NIDM format. As a BIDS App, it processes **one subject per container run**, creating a unified output structure under `mriqc_nidm/` with separate `mriqc/` and `nidm/` subdirectories.

```bash
mriqc-nidm <bids_dir> <output_dir> participant --participant-label <subject_id> [options]
```

### Required Arguments

- `bids_dir`: Path to BIDS dataset directory
- `output_dir`: Path to output directory  
- `analysis_level`: Must be `participant`
- `--participant-label`: **Required** - Single subject to process (without 'sub-' prefix)

### Optional Arguments

- `--nidm-input-dir`: Override default NIDM input location (default: BIDS_DIR/../NIDM/)
- `--skip-mriqc`: Skip MRIQC execution, use existing output
- `--mriqc-output-dir`: Use existing MRIQC output directory
- `--skip-nidm-conversion`: Run MRIQC only, skip NIDM conversion
- `--nidm-mode`: NIDM processing mode (generate|update|convert)
- `-v, --verbose`: Enable verbose output
- `--version`: Show version information

### NIDM Processing Modes

- **`generate`** (default): Create new NIDM files from MRIQC outputs
- **`update`**: Augment existing NIDM files with new MRIQC data (copies existing file first)
- **`convert`**: Convert existing NIDM files to different formats only

### Output Structure

```
output_dir/
└── mriqc_nidm/              # All outputs packaged together
    ├── mriqc/               # MRIQC outputs (JSON, HTML, figures)
    │   └── sub-{id}/
    └── nidm/                # NIDM outputs (TTL, JSON-LD, CSV)
        ├── dataset_description.json
        └── sub-{id}/
```

The unified structure ensures all outputs are packaged together in BABS workflows. The app automatically copies existing NIDM files to the output folder before modification, ensuring the original is never overwritten.

### Example: Process Single Subject

```bash
# Process subject 001 with Docker
docker run -v /path/to/bids:/data -v /path/to/output/sub-001:/out \
    mriqc-nidm /data /out participant --participant-label 001

# Process multiple subjects (run once per subject)
for subj in 001 002 003; do
    docker run -v /path/to/bids:/data -v /path/to/output/sub-$subj:/out \
        mriqc-nidm /data /out participant --participant-label $subj
done
```

## License

See the [LICENSE](LICENSE) file for details.
