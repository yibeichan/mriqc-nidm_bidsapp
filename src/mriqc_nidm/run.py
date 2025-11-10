#!/usr/bin/env python3
"""
Main entry point for MRIQC-NIDM BIDSAPP.

This module orchestrates the complete workflow:
1. Detect existing NIDM files (optional)
2. Run MRIQC quality control
3. Convert MRIQC JSON outputs to CSV
4. Convert CSV to NIDM format
5. Support augmentation of existing NIDM files

Follows BIDS Apps specification and patterns from freesurfer_bidsapp.
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from . import __version__
from .csv_to_nidm import check_csv2nidm_available, convert_csv_to_nidm
from .data import get_mriqc_dictionary
from .json_to_csv import convert_mriqc_json_to_csv
from .mriqc_wrapper import MRIQCWrapper
from .nidm_handler import (
    _search_nidm_in_directory,
    convert_nidm_formats,
    copy_nidm_to_output,
    detect_existing_nidm,
)


def setup_logging(output_dir: Path, verbose: bool = False) -> logging.Logger:
    """
    Set up logging configuration.

    Args:
        output_dir: Output directory for log files
        verbose: Enable verbose (DEBUG) logging

    Returns:
        Configured logger instance
    """
    log_dir = output_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_file = log_dir / f"mriqc-nidm-{timestamp}.log"

    level = logging.DEBUG if verbose else logging.INFO

    # Configure root logger
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
    )

    logger = logging.getLogger("mriqc-nidm")
    logger.info(f"MRIQC-NIDM BIDSAPP version {__version__}")
    logger.info(f"Log file: {log_file}")

    return logger


def create_dataset_description(output_dir: Path, logger: logging.Logger) -> Path:
    """
    Create dataset_description.json for NIDM derivatives.

    Args:
        output_dir: Output directory
        logger: Logger instance

    Returns:
        Path to created dataset_description.json
    """
    nidm_dir = output_dir / "nidm"
    nidm_dir.mkdir(parents=True, exist_ok=True)

    dataset_desc = {
        "Name": "MRIQC Quality Control Metrics (NIDM)",
        "BIDSVersion": "1.6.0",
        "DatasetType": "derivative",
        "GeneratedBy": [
            {
                "Name": "MRIQC-NIDM BIDSAPP",
                "Version": __version__,
                "CodeURL": "https://github.com/yibeichan/mriqc-nidm_bidsapp",
            }
        ],
        "HowToAcknowledge": "Please cite MRIQC (https://doi.org/10.1371/journal.pone.0184661) and NIDM (http://nidm.nidash.org/)",
    }

    desc_file = nidm_dir / "dataset_description.json"
    with open(desc_file, "w") as f:
        json.dump(dataset_desc, f, indent=2)

    logger.info(f"Created dataset description: {desc_file}")
    return desc_file


def process_subject(
    subject_id: str,
    bids_dir: Path,
    output_dir: Path,
    mriqc_dir: Path,
    nidm_input_dir: Optional[Path],
    skip_mriqc: bool,
    skip_nidm: bool,
    logger: logging.Logger,
) -> bool:
    """
    Process a single subject through the MRIQC → NIDM pipeline.

    Args:
        subject_id: Subject identifier (without 'sub-' prefix)
        bids_dir: BIDS dataset directory
        output_dir: Output directory
        mriqc_dir: MRIQC output directory
        nidm_input_dir: Optional NIDM input directory
        skip_mriqc: Skip MRIQC execution (use existing output)
        skip_nidm: Skip NIDM conversion
        logger: Logger instance

    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Processing subject: sub-{subject_id}")

    try:
        # Step 1: Detect existing NIDM input
        existing_nidm = None
        if nidm_input_dir:
            # Custom NIDM input directory specified
            # Use shared search logic to ensure consistency
            nidm_input_subject_dir = nidm_input_dir / f"sub-{subject_id}"
            existing_nidm = _search_nidm_in_directory(nidm_input_subject_dir, logger)
        else:
            # Convention-based location: BIDS/../NIDM/
            existing_nidm = detect_existing_nidm(bids_dir, subject_id, logger)

        # Step 2: Find MRIQC outputs
        # Look for MRIQC JSON files in the MRIQC output directory
        subject_mriqc_dir = mriqc_dir / f"sub-{subject_id}"

        if not subject_mriqc_dir.exists():
            logger.warning(f"No MRIQC output directory found for sub-{subject_id}: {subject_mriqc_dir}")
            return False

        # Find all MRIQC JSON files recursively
        # This handles both session and non-session datasets:
        # - Non-session: sub-01/anat/*.json, sub-01/func/*.json
        # - Session: sub-01/ses-01/anat/*.json, sub-01/ses-01/func/*.json
        # Sort for deterministic processing order
        json_files = sorted(subject_mriqc_dir.rglob("*.json"))

        if not json_files:
            logger.warning(f"No MRIQC JSON files found for sub-{subject_id}")
            return False

        logger.info(f"Found {len(json_files)} MRIQC JSON file(s) for sub-{subject_id}")

        if skip_nidm:
            logger.info("Skipping NIDM conversion (--skip-nidm-conversion flag)")
            return True

        # Step 3: Process each MRIQC JSON file
        nidm_output_subject_dir = output_dir / "nidm" / f"sub-{subject_id}"
        nidm_output_subject_dir.mkdir(parents=True, exist_ok=True)

        # Get data dictionary path
        dictionary_csv = get_mriqc_dictionary()

        # Step 3a: Copy existing NIDM ONCE (before loop) if available
        # CRITICAL: Must copy once before loop, not inside loop!
        # Otherwise each iteration overwrites previous augmentations
        copied_nidm = None
        if existing_nidm:
            copied_nidm = copy_nidm_to_output(
                existing_nidm, nidm_output_subject_dir, logger
            )
            logger.info(f"Will augment existing NIDM: {copied_nidm}")

        # Track failures to return accurate status
        any_scan_failed = False

        for json_file in json_files:
            logger.info(f"Converting {json_file.name}")

            # Step 3b: Convert JSON → CSV
            csv_file = nidm_output_subject_dir / f"{json_file.stem}.csv"
            try:
                csv_path, software_csv_path = convert_mriqc_json_to_csv(
                    json_file, csv_file, logger
                )
            except Exception as e:
                logger.error(f"Failed to convert {json_file.name} to CSV: {e}")
                any_scan_failed = True
                continue

            # Step 3c: Convert CSV → NIDM
            # If augmenting, use the copied NIDM file (already copied before loop)
            # If standalone, create new file for this JSON
            if copied_nidm:
                # Augmentation mode: All JSONs augment the same copied NIDM
                ttl_file = copied_nidm
            else:
                # Standalone mode: Create separate TTL for each JSON
                ttl_file = nidm_output_subject_dir / f"{json_file.stem}.ttl"

            try:
                success = convert_csv_to_nidm(
                    csv_file=csv_path,
                    dictionary_csv=dictionary_csv,
                    software_metadata_csv=software_csv_path,
                    output_ttl=ttl_file,
                    existing_nidm=copied_nidm,  # Augment if available
                    logger=logger,
                )

                if not success:
                    logger.error(f"Failed to convert {csv_path.name} to NIDM")
                    any_scan_failed = True
                    continue

            except Exception as e:
                logger.error(f"Error during NIDM conversion: {e}")
                any_scan_failed = True
                continue

            # Step 3d: Convert to multiple formats (.ttl and .jsonld)
            # Only do this for standalone mode (one file per JSON)
            if not copied_nidm:
                try:
                    ttl_path, jsonld_path = convert_nidm_formats(
                        ttl_file, nidm_output_subject_dir, subject_id, logger
                    )
                    logger.info(f"Created NIDM outputs: {ttl_path.name}, {jsonld_path.name}")
                except Exception as e:
                    logger.warning(f"Failed to create JSON-LD format: {e}")
                    # TTL file already exists, so this is not critical

        # Step 3e: For augmentation mode, convert final NIDM to formats ONCE
        if copied_nidm:
            try:
                ttl_path, jsonld_path = convert_nidm_formats(
                    copied_nidm, nidm_output_subject_dir, subject_id, logger
                )
                logger.info(f"Created augmented NIDM outputs: {ttl_path.name}, {jsonld_path.name}")
            except Exception as e:
                logger.warning(f"Failed to create JSON-LD format: {e}")

        if any_scan_failed:
            logger.warning(f"Some scans failed to process for subject: sub-{subject_id}")
            return False

        logger.info(f"Successfully processed subject: sub-{subject_id}")
        return True

    except Exception as e:
        logger.error(f"Error processing subject sub-{subject_id}: {e}", exc_info=True)
        return False


def main():
    """Main entry point for MRIQC-NIDM BIDSAPP."""
    parser = argparse.ArgumentParser(
        description="MRIQC-NIDM BIDS App - Execute MRIQC and convert to NIDM format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Required positional arguments (BIDS Apps standard)
    parser.add_argument(
        "bids_dir",
        type=Path,
        help="Path to BIDS dataset directory",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        help="Path to output directory",
    )
    parser.add_argument(
        "analysis_level",
        choices=["participant"],
        help="Analysis level (currently only 'participant' is supported)",
    )

    # Optional arguments
    parser.add_argument(
        "--participant-label",
        nargs="+",
        help="Subject label(s) to process (without 'sub-' prefix)",
    )
    parser.add_argument(
        "--nidm-input-dir",
        type=Path,
        help="Override default NIDM input location (default: BIDS_DIR/../NIDM/)",
    )
    parser.add_argument(
        "--skip-mriqc",
        action="store_true",
        help="Skip MRIQC execution, use existing output",
    )
    parser.add_argument(
        "--mriqc-output-dir",
        type=Path,
        help="Use existing MRIQC output directory (implies --skip-mriqc)",
    )
    parser.add_argument(
        "--skip-nidm-conversion",
        action="store_true",
        help="Run MRIQC only, skip NIDM conversion",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"MRIQC-NIDM BIDSAPP v{__version__}",
    )

    args = parser.parse_args()

    # Validate paths
    if not args.bids_dir.exists():
        print(f"Error: BIDS directory not found: {args.bids_dir}", file=sys.stderr)
        return 1

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Setup logging
    logger = setup_logging(args.output_dir, args.verbose)

    # Check for required tools
    if not args.skip_nidm_conversion and not check_csv2nidm_available():
        logger.error(
            "csv2nidm tool not found. Please ensure PyNIDM is installed. "
            "Install with: pip install pynidm"
        )
        return 1

    # Determine MRIQC output directory
    if args.mriqc_output_dir:
        mriqc_dir = args.mriqc_output_dir
        skip_mriqc = True
        logger.info(f"Using existing MRIQC output: {mriqc_dir}")
    else:
        mriqc_dir = args.output_dir / "mriqc"
        skip_mriqc = args.skip_mriqc

    # Validate MRIQC directory if skipping execution
    if skip_mriqc and not mriqc_dir.exists():
        logger.error(
            f"MRIQC output directory not found: {mriqc_dir}. "
            "This is required when --skip-mriqc or --mriqc-output-dir is used."
        )
        return 1

    # Get list of subjects to process
    if args.participant_label:
        subjects = args.participant_label
    else:
        # Find all subjects in MRIQC output (if exists) or BIDS directory
        if mriqc_dir.exists():
            subjects = [d.name[4:] for d in mriqc_dir.glob("sub-*") if d.is_dir()]
        else:
            subjects = [d.name[4:] for d in args.bids_dir.glob("sub-*") if d.is_dir()]

    if not subjects:
        logger.error("No subjects found to process")
        return 1

    logger.info(f"Processing {len(subjects)} subject(s): {', '.join(subjects)}")

    # Run MRIQC if not skipped
    if not skip_mriqc:
        logger.info("Running MRIQC quality control...")
        try:
            mriqc_wrapper = MRIQCWrapper(
                bids_dir=args.bids_dir,
                output_dir=args.output_dir,
            )

            # Process participants
            for subject_id in subjects:
                logger.info(f"Running MRIQC for sub-{subject_id}")
                try:
                    mriqc_wrapper.process_participant(
                        subject_id=subject_id,
                        verbose_count=1 if args.verbose else 0,
                    )
                except Exception as e:
                    logger.error(f"MRIQC failed for sub-{subject_id}: {e}")
                    continue

            logger.info("MRIQC execution completed")

        except Exception as e:
            logger.error(f"MRIQC execution failed: {e}", exc_info=True)
            return 1

    # Process each subject through NIDM conversion
    success_count = 0
    for subject_id in subjects:
        if process_subject(
            subject_id=subject_id,
            bids_dir=args.bids_dir,
            output_dir=args.output_dir,
            mriqc_dir=mriqc_dir,
            nidm_input_dir=args.nidm_input_dir,
            skip_mriqc=skip_mriqc,
            skip_nidm=args.skip_nidm_conversion,
            logger=logger,
        ):
            success_count += 1

    # Create dataset description
    if not args.skip_nidm_conversion:
        create_dataset_description(args.output_dir, logger)

    # Summary
    logger.info(f"Processing complete: {success_count}/{len(subjects)} subjects successful")

    if success_count == len(subjects):
        logger.info("All subjects processed successfully")
        return 0
    elif success_count > 0:
        logger.warning("Some subjects failed to process")
        return 1
    else:
        logger.error("All subjects failed to process")
        return 1


if __name__ == "__main__":
    sys.exit(main())
