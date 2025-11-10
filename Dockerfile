FROM nipreps/mriqc:latest

# Install minimal system dependencies (conda already provides Python/pip)
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# =======================================
# Environment Configuration
# =======================================
ENV PYTHONPATH=/opt:$PYTHONPATH
ENV PATH=/usr/local/bin:$PATH

# =======================================
# BIDS App Setup
# =======================================
# Copy application files to /opt
COPY . /opt/

# Install Python dependencies using conda/pip hybrid approach
WORKDIR /opt

# Install conda-forge packages with micromamba (better dependency resolution)
RUN micromamba install -n base -y -c conda-forge \
    pandas \
    rdflib \
    click \
    pybids

# Install PyPI-only packages using pip (from conda environment)
RUN pip install --no-cache-dir pynidm nidmresults

# Install mriqc-nidm package in editable mode
RUN pip install -e .

# =======================================
# Runtime Configuration
# =======================================
# Entrypoint that expects input/output paths as arguments
ENTRYPOINT ["python3", "/opt/src/mriqc_nidm/run.py"]
