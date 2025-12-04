#!/usr/bin/env python3
"""
Combine HTML files from multiple WARC extractions by domain.
For files that exist in multiple folders (same domain, same path),
keep the one with the newest timestamp.
"""

import os
import re
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import json


def extract_timestamp_and_domain(folder_name):
    """
    Extract timestamp and domain from folder name.
    Format: {WARC_FILENAME}_{DOMAIN}
    Timestamp in WARC filename: YYYYMMDDHHMMSSmmm

    Example: ARCHIVEIT-19945-TEST-JOB2538000-0-SEED4432727-20250409125201867-00000-9618ziof.warc.gz_hytac.arch.ethz.ch
    Returns: (datetime_object, 'hytac.arch.ethz.ch')
    """
    # Split by last underscore to separate WARC filename from domain
    parts = folder_name.rsplit('_', 1)
    if len(parts) != 2:
        return None, None

    warc_filename, domain = parts

    # Extract timestamp from WARC filename (format: YYYYMMDDHHMMSS followed by milliseconds)
    # Look for pattern: 14 digits followed by optional digits
    timestamp_match = re.search(r'-(\d{14})\d*-', warc_filename)
    if not timestamp_match:
        return None, domain

    timestamp_str = timestamp_match.group(1)

    try:
        timestamp = datetime.strptime(timestamp_str, '%Y%m%d%H%M%S')
        return timestamp, domain
    except ValueError:
        return None, domain


def scan_html_folders(input_dir):
    """
    Scan all folders and organize by domain.
    Returns: dict mapping domain -> list of (timestamp, folder_path) tuples
    """
    domain_folders = defaultdict(list)

    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Error: Input directory {input_dir} does not exist")
        return domain_folders

    for folder in input_path.iterdir():
        if not folder.is_dir():
            continue

        timestamp, domain = extract_timestamp_and_domain(folder.name)
        if domain:
            domain_folders[domain].append((timestamp, folder))
            print(f"Found: {domain} - {timestamp} - {folder.name}")

    return domain_folders


def get_all_files_in_folder(folder_path):
    """
    Get all HTML files in a folder with their relative paths.
    Returns: dict mapping relative_path -> absolute_path
    """
    files = {}
    folder_path = Path(folder_path)

    for file_path in folder_path.rglob('*'):
        if file_path.is_file():
            relative_path = file_path.relative_to(folder_path)
            files[str(relative_path)] = file_path

    return files


def combine_domain_folders(domain, folder_list, output_dir):
    """
    Combine multiple folders for the same domain.
    For duplicate files, keep the one with the newest timestamp.
    Returns file count and timestamp metadata.
    """
    print(f"\nProcessing domain: {domain}")
    print(f"  Found {len(folder_list)} folders")

    # Create output directory for this domain
    output_path = Path(output_dir) / domain
    output_path.mkdir(parents=True, exist_ok=True)

    # Track which file to use for each relative path
    file_registry = {}  # relative_path -> (timestamp, source_absolute_path)

    # Process each folder for this domain
    for timestamp, folder_path in folder_list:
        files = get_all_files_in_folder(folder_path)

        for relative_path, absolute_path in files.items():
            # If we haven't seen this file yet, or this version is newer
            if relative_path not in file_registry:
                file_registry[relative_path] = (timestamp, absolute_path)
                print(f"  + {relative_path} (from {timestamp})")
            else:
                existing_timestamp, _ = file_registry[relative_path]

                # If timestamp is None, we can't compare, so keep the existing one
                if timestamp is None:
                    continue
                if existing_timestamp is None:
                    file_registry[relative_path] = (timestamp, absolute_path)
                    print(f"  ↑ {relative_path} (updated to {timestamp})")
                elif timestamp > existing_timestamp:
                    file_registry[relative_path] = (timestamp, absolute_path)
                    print(f"  ↑ {relative_path} (updated: {existing_timestamp} -> {timestamp})")

    # Copy all selected files to output directory and build metadata
    print(f"\n  Copying {len(file_registry)} files to {output_path}")
    timestamp_metadata = {}

    for relative_path, (timestamp, source_path) in file_registry.items():
        dest_path = output_path / relative_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)

        # Store timestamp metadata
        # Key: domain/relative_path, Value: ISO timestamp string
        file_key = f"{domain}/{relative_path}"
        timestamp_metadata[file_key] = timestamp.isoformat() if timestamp else None

    print(f"  ✓ Completed {domain}")
    return len(file_registry), timestamp_metadata


def combine_domains_by_timestamp(input_dir, output_dir, timestamps_json_path=None):
    """
    Combine HTML files from multiple WARC extractions by domain.
    For files that exist in multiple folders (same domain, same path),
    keep the one with the newest timestamp.

    Args:
        input_dir (str): Directory containing the extracted WARC folders (e.g., "output/html_raw")
        output_dir (str): Directory where combined results will be saved (e.g., "output/html_combined")
        timestamps_json_path (str, optional): Path to save file timestamp metadata JSON.
            If None, saves to "{output_dir}_timestamps.json"

    Returns:
        dict: Summary with keys 'domains_count', 'total_files', 'domains', and 'timestamps_file'
    """
    print("=" * 70)
    print("Domain HTML Combiner")
    print("=" * 70)
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    print("=" * 70)

    # Scan folders and organize by domain
    domain_folders = scan_html_folders(input_dir)

    if not domain_folders:
        print("\nNo valid folders found!")
        return {
            'domains_count': 0,
            'total_files': 0,
            'domains': [],
            'timestamps_file': None
        }

    print(f"\n\nFound {len(domain_folders)} unique domains")
    print("=" * 70)

    # Process each domain
    total_files = 0
    processed_domains = []
    all_timestamps = {}

    for domain, folder_list in sorted(domain_folders.items()):
        # Sort by timestamp (None values go first)
        folder_list.sort(key=lambda x: x[0] if x[0] is not None else datetime.min)

        files_count, timestamp_metadata = combine_domain_folders(domain, folder_list, output_dir)
        total_files += files_count
        processed_domains.append(domain)
        all_timestamps.update(timestamp_metadata)

    # Save timestamp metadata to JSON
    if timestamps_json_path is None:
        timestamps_json_path = f"{output_dir}_timestamps.json"

    timestamps_path = Path(timestamps_json_path)
    timestamps_path.parent.mkdir(parents=True, exist_ok=True)

    with open(timestamps_path, 'w', encoding='utf-8') as f:
        json.dump(all_timestamps, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print(f"✓ Successfully combined {len(domain_folders)} domains")
    print(f"✓ Total files: {total_files}")
    print(f"✓ Output directory: {output_dir}")
    print(f"✓ Timestamps saved to: {timestamps_json_path}")
    print("=" * 70)

    return {
        'domains_count': len(domain_folders),
        'total_files': total_files,
        'domains': processed_domains,
        'timestamps_file': str(timestamps_json_path)
    }


def main():
    """Main function to combine domains with default paths."""
    # Configuration
    input_dir = "output/html_raw/19945"
    output_dir = "output/html_combined"

    combine_domains_by_timestamp(input_dir, output_dir)


if __name__ == "__main__":
    main()
