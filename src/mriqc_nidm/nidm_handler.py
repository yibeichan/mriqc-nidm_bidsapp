#!/usr/bin/env python
"""
NIDM Handler for MRIQC-NIDM BIDSAPP

This module handles existing NIDM file detection, copying, and format conversion.
Follows patterns from freesurfer_bidsapp/src/run.py for NIDM augmentation workflow.

Key features:
- Detects existing NIDM files following BIDS/../NIDM/ convention
- Safely copies existing NIDM to output directory
- Converts between Turtle (.ttl) and JSON-LD (.jsonld) formats
- Supports NIDM augmentation workflow (adding MRIQC data to existing NIDM)

Author: Adapted from freesurfer_bidsapp for mriqc-nidm_bidsapp
"""

import logging
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from rdflib import Graph
from rdflib.exceptions import ParserError
from rdflib.plugin import PluginException


# Module-level constant for supported NIDM file extensions
SUPPORTED_NIDM_EXTENSIONS = [".ttl", ".jsonld", ".json-ld"]


def detect_existing_nidm(
    bids_dir: Path, subject_id: str, logger: Optional[logging.Logger] = None
) -> Optional[Path]:
    """
    Detect existing NIDM file for subject following freesurfer_bidsapp pattern.

    Searches for NIDM files in the convention-based location: BIDS_DIR/../NIDM/sub-{subject_id}/
    This follows the pattern used by freesurfer_bidsapp and other NIDM-producing BIDSAPPs.

    Search order (first match returned):
    1. nidm.ttl (preferred)
    2. Any *.ttl file
    3. Any *.jsonld file
    4. Any *.json-ld file

    Args:
        bids_dir: Path to BIDS dataset directory
        subject_id: Subject identifier (without "sub-" prefix)
        logger: Optional logger instance

    Returns:
        Path to existing NIDM file, or None if not found

    Examples:
        >>> detect_existing_nidm(Path('/data/BIDS'), '01', logger)
        Path('/data/NIDM/sub-01/nidm.ttl')

        >>> detect_existing_nidm(Path('/data/BIDS'), '99', logger)
        None  # No NIDM files found

    Notes:
        - Returns None if NIDM directory doesn't exist (not an error)
        - Logs INFO when NIDM file found, DEBUG when not found
        - Uses pathlib for cross-platform compatibility
    """
    # Setup default logger if not provided
    if logger is None:
        logger = logging.getLogger(__name__)

    # Convention: NIDM files are in BIDS_DIR/../NIDM/sub-{subject_id}/
    nidm_input_dir = bids_dir.parent / "NIDM" / f"sub-{subject_id}"

    if not nidm_input_dir.exists():
        logger.debug(f"No NIDM input directory found at: {nidm_input_dir}")
        return None

    logger.debug(f"Searching for existing NIDM in: {nidm_input_dir}")

    # Search order: nidm.ttl > *.ttl > *.jsonld > *.json-ld
    preferred = nidm_input_dir / "nidm.ttl"
    if preferred.exists():
        logger.info(f"Found existing NIDM (preferred): {preferred}")
        return preferred

    # Search for other NIDM formats in order of preference
    # Sort results for deterministic behavior across filesystems
    for ext in SUPPORTED_NIDM_EXTENSIONS:
        files = sorted(nidm_input_dir.glob(f"*{ext}"))
        if files:
            logger.info(f"Found existing NIDM ({ext.lstrip('.')}): {files[0]}")
            return files[0]

    logger.debug(f"No NIDM files found in: {nidm_input_dir}")
    return None


def copy_nidm_to_output(
    existing_nidm: Path,
    output_dir: Path,
    logger: Optional[logging.Logger] = None,
) -> Path:
    """
    Safely copy existing NIDM file to output directory.

    This function ensures that the input NIDM file is never modified by
    copying it to the output directory first. Follows the safety-first
    pattern from freesurfer_bidsapp.

    Args:
        existing_nidm: Path to existing NIDM file
        output_dir: Path to output directory
        logger: Optional logger instance

    Returns:
        Path to copied NIDM file in output directory

    Raises:
        FileNotFoundError: If existing_nidm doesn't exist
        OSError: If copy operation fails

    Examples:
        >>> copy_nidm_to_output(
        ...     Path('/data/NIDM/sub-01/nidm.ttl'),
        ...     Path('/output/nidm'),
        ...     logger
        ... )
        Path('/output/nidm/nidm.ttl')

    Notes:
        - Creates output directory if it doesn't exist
        - Preserves file metadata (timestamps, permissions)
        - Safety check prevents overwriting input file
        - Uses shutil.copy2 for metadata preservation
    """
    # Setup default logger if not provided
    if logger is None:
        logger = logging.getLogger(__name__)

    # Validate input file exists
    if not existing_nidm.exists():
        logger.error(f"Existing NIDM file not found: {existing_nidm}")
        raise FileNotFoundError(f"NIDM file not found: {existing_nidm}")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    # Determine output path (preserve original filename)
    output_path = output_dir / existing_nidm.name

    # Safety check: don't copy if paths are the same
    try:
        if existing_nidm.resolve() == output_path.resolve():
            logger.info(f"Input and output NIDM paths are identical: {output_path}")
            logger.info("Skipping copy to avoid unnecessary operation")
            return output_path
    except (FileNotFoundError, RuntimeError, OSError) as e:
        logger.warning(f"Could not compare paths: {e}")

    # Copy file with metadata preservation
    try:
        shutil.copy2(existing_nidm, output_path)
        logger.info(f"Copied existing NIDM to output: {output_path}")
        return output_path
    except OSError as e:
        logger.error(f"Failed to copy NIDM file: {e}")
        logger.error(f"  Source: {existing_nidm}")
        logger.error(f"  Destination: {output_path}")
        raise OSError(f"Failed to copy NIDM file: {e}") from e


def convert_nidm_formats(
    input_file: Path,
    output_dir: Path,
    subject_id: str,
    logger: Optional[logging.Logger] = None,
) -> Tuple[Path, Path]:
    """
    Convert NIDM to multiple formats (.ttl and .jsonld).

    Uses rdflib to parse the input NIDM file and serialize to both
    Turtle (.ttl) and JSON-LD (.jsonld) formats for maximum interoperability.

    Args:
        input_file: Path to input NIDM file (any RDF format)
        output_dir: Path to output directory
        subject_id: Subject identifier (without "sub-" prefix)
        logger: Optional logger instance

    Returns:
        Tuple of (ttl_path, jsonld_path)

    Raises:
        FileNotFoundError: If input_file doesn't exist
        Exception: If RDF parsing or serialization fails

    Examples:
        >>> convert_nidm_formats(
        ...     Path('/temp/nidm.ttl'),
        ...     Path('/output/nidm'),
        ...     '01',
        ...     logger
        ... )
        (Path('/output/nidm/sub-01.ttl'), Path('/output/nidm/sub-01.jsonld'))

    Notes:
        - Automatically detects input format using rdflib
        - Output filenames include subject ID: sub-{subject_id}.ttl
        - Creates output directory if it doesn't exist
        - Preserves all RDF triples during conversion
        - JSON-LD format is useful for web applications
        - Turtle format is preferred for human readability
    """
    # Setup default logger if not provided
    if logger is None:
        logger = logging.getLogger(__name__)

    # Validate input file exists
    if not input_file.exists():
        logger.error(f"Input NIDM file not found: {input_file}")
        raise FileNotFoundError(f"NIDM file not found: {input_file}")

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Converting NIDM formats for subject: {subject_id}")
    logger.debug(f"  Input: {input_file}")

    try:
        # Load RDF graph (rdflib auto-detects format)
        graph = Graph()
        graph.parse(input_file)
        logger.debug(f"  Loaded {len(graph)} RDF triples")

        # Define output paths
        ttl_output = output_dir / f"sub-{subject_id}.ttl"
        jsonld_output = output_dir / f"sub-{subject_id}.jsonld"

        # Serialize to Turtle format
        graph.serialize(destination=str(ttl_output), format="turtle")
        logger.info(f"  Created Turtle: {ttl_output}")

        # Serialize to JSON-LD format
        graph.serialize(destination=str(jsonld_output), format="json-ld")
        logger.info(f"  Created JSON-LD: {jsonld_output}")

        return ttl_output, jsonld_output

    except (OSError, ParserError, PluginException) as e:
        logger.error(f"Failed to convert NIDM formats: {e}")
        logger.error(f"  Input file: {input_file}")
        raise RuntimeError(f"NIDM format conversion failed: {e}") from e


def get_supported_nidm_formats() -> List[str]:
    """
    Get list of supported NIDM file extensions.

    Returns:
        List of file extensions (with dots)

    Examples:
        >>> get_supported_nidm_formats()
        ['.ttl', '.jsonld', '.json-ld']
    """
    return SUPPORTED_NIDM_EXTENSIONS


def is_nidm_file(file_path: Path) -> bool:
    """
    Check if file is a supported NIDM format.

    Args:
        file_path: Path to file

    Returns:
        True if file has supported NIDM extension

    Examples:
        >>> is_nidm_file(Path('data.ttl'))
        True

        >>> is_nidm_file(Path('data.csv'))
        False
    """
    return file_path.suffix in SUPPORTED_NIDM_EXTENSIONS
