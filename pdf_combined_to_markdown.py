#!/usr/bin/env python3
"""
Convert PDF files from pdf_combined directory to markdown files.
Filters domains based on Excel sheet and maintains folder structure.
Creates one markdown file per PDF.
"""

import os
import json
import gzip
import re
from pathlib import Path
from tqdm import tqdm
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from functools import partial
import multiprocessing as mp


def get_base_site_from_url(url_in):
    """
    Extracts the base site from the given URL.
    Example: "http://ethz.ch/about/test.png" returns "ethz.ch"
    """
    if "//" not in url_in:
        base_site = url_in
    else:
        url_in_old = url_in
        base_site = url_in.split("//")[1]
        if base_site == "http:":
            print(f"This url is oddly formed: {url_in_old}")
            base_site = url_in_old.split("//")[2]

    base_site = base_site.replace("dns:", "")
    base_site = base_site.replace("mailto:", "")
    base_site = base_site.replace("www.", "")
    base_site = base_site.replace("www0.", "")
    base_site = base_site.replace("www1.", "")
    base_site = base_site.replace("www2.", "")
    base_site = base_site.replace("www3.", "")
    base_site = base_site.split(":")[0]
    base_site = base_site.split("/")[0]

    if base_site[-1] == ".":
        base_site = base_site[:-1]

    return base_site


def get_base_url_from_url(url_in):
    """
    Extracts the base URL (protocol + domain) from a full URL.
    """
    if "//" not in url_in:
        return url_in

    parts = url_in.split("//")
    protocol = parts[0] + "//"
    rest = parts[1]
    domain = rest.split("/")[0]

    return protocol + domain


def load_allowed_domains(excel_path):
    """
    Load allowed domains from Excel file.
    """
    df = pd.read_excel(excel_path)
    df = df.fillna("")
    urls = list(df["URL"])

    allowed_domains = set()
    for url in urls:
        if url != "":
            base_site = get_base_site_from_url(url)
            allowed_domains.add(base_site)

    print(f"Loaded {len(allowed_domains)} allowed domains from Excel")
    return allowed_domains


def convert_pdf_to_markdown(pdf_path, output_path, create_dirs=True):
    """
    Convert a single PDF file to markdown.

    Args:
        pdf_path (Path): Path to PDF file
        output_path (Path): Path where markdown should be saved
        create_dirs (bool): Whether to create directories (set False if pre-created)

    Returns:
        str: 'converted' if successful, 'skipped' if intentionally skipped, 'failed' if error
    """
    try:
        import fitz  # PyMuPDF

        # Read PDF file (handle both regular and gzipped)
        if str(pdf_path).endswith('.gz'):
            with gzip.open(pdf_path, 'rb') as f:
                pdf_bytes = f.read()
                pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        else:
            pdf_doc = fitz.open(str(pdf_path))

        if pdf_doc.page_count == 0:
            pdf_doc.close()
            return 'skipped'  # Empty PDF - intentional skip

        # Extract text from all pages
        text_parts = []
        for page_num, page in enumerate(pdf_doc):
            page_text = page.get_text()
            if page_text.strip():
                # Add page header in markdown
                text_parts.append(f"## Page {page_num + 1}\n\n{page_text}\n")

        pdf_doc.close()

        # Combine all text
        pdf_text = "\n".join(text_parts)

        # Clean up text
        pdf_text = re.sub("¬\n", "", pdf_text)  # Remove soft hyphens
        pdf_text = re.sub(r'\\', "", pdf_text)  # Remove backslashes
        pdf_text = pdf_text.strip()

        # Skip empty files
        if not pdf_text or pdf_text == "":
            return 'skipped'  # No extractable text - intentional skip

        # Create output directory if needed
        if create_dirs:
            output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write markdown file
        with open(output_path, 'w', encoding='utf-8') as f:
            # Add metadata header
            f.write(f"# PDF Document: {pdf_path.name}\n\n")
            f.write(pdf_text)

        return 'converted'  # Success

    except Exception as e:
        return 'failed'  # General error - conversion failure


def process_single_pdf_file(args):
    """
    Process a single PDF file (for parallel execution).

    Args:
        args: Tuple of (pdf_file, domain_folder, output_path, filenames_to_remove)

    Returns:
        tuple: (status, count) where status is 'converted', 'skipped', or 'failed'
    """
    pdf_file, domain_folder, output_path, filenames_to_remove = args

    # Check if filename should be skipped
    for keyword in filenames_to_remove:
        if keyword in pdf_file.name.lower():
            return ('skipped', 1)

    # Calculate relative path from domain folder
    rel_path = pdf_file.relative_to(domain_folder)

    # Create output path (change extension to .md)
    if str(pdf_file).endswith('.pdf.gz'):
        md_filename = pdf_file.name.replace('.pdf.gz', '.md')
    else:
        md_filename = pdf_file.stem + '.md'

    output_file_path = output_path / domain_folder.name / rel_path.parent / md_filename

    # Convert PDF to markdown (dirs already created in batch)
    status = convert_pdf_to_markdown(pdf_file, output_file_path, create_dirs=False)
    return (status, 1)


def process_domain_parallel(domain_folder, input_path, output_path, allowed_domains, filenames_to_remove, max_workers=None):
    """
    Process all PDF files in a domain folder in parallel.

    Args:
        domain_folder (Path): Domain folder to process
        input_path (Path): Input base path
        output_path (Path): Output base path
        allowed_domains (set): Set of allowed domains (or None)
        filenames_to_remove (list): Keywords to skip
        max_workers (int, optional): Number of thread workers for file I/O. If None, uses CPU count.

    Returns:
        dict: Results with 'domain', 'converted', 'skipped', 'failed' counts
    """
    domain = domain_folder.name

    # Check if domain is in allowed list (if filtering is enabled)
    if allowed_domains is not None and domain not in allowed_domains:
        return {'domain': domain, 'converted': 0, 'skipped': 0, 'failed': 0}

    # Collect all PDF files in this domain folder
    pdf_files = []
    for pdf_file in domain_folder.rglob('*'):
        if not pdf_file.is_file():
            continue
        # Check if it's a PDF file
        if pdf_file.suffix == '.pdf' or str(pdf_file).endswith('.pdf.gz'):
            pdf_files.append(pdf_file)

    if not pdf_files:
        return {'domain': domain, 'converted': 0, 'skipped': 0, 'failed': 0}

    # Prepare arguments for parallel processing
    file_args = [(f, domain_folder, output_path, filenames_to_remove) for f in pdf_files]

    converted = 0
    skipped = 0
    failed = 0

    # Determine number of workers for files within this domain
    file_workers = max_workers if max_workers is not None else mp.cpu_count()

    # Process files in parallel using threads (I/O bound)
    try:
        with ThreadPoolExecutor(max_workers=file_workers) as executor:
            for status, count in executor.map(process_single_pdf_file, file_args):
                if status == 'converted':
                    converted += count
                elif status == 'skipped':
                    skipped += count
                else:  # 'failed'
                    failed += count
    except Exception as e:
        print(f"Error in thread pool for domain {domain}: {e}")
        # Mark remaining files as failed
        failed += len(file_args) - (converted + skipped + failed)

    return {'domain': domain, 'converted': converted, 'skipped': skipped, 'failed': failed}


def convert_pdf_combined_to_markdown(
    input_dir,
    output_dir,
    excel_path=None,
    mappings_path=None,
    filenames_to_remove=[
        "impressum", "datenschutz", "kontakt", "robots",
        "imprint", "data-protection", "contact", "copyright",
    ],
    max_domain_workers=None,
    max_file_workers=None
):
    """
    Convert PDF files from pdf_combined directory to markdown files.
    Creates one markdown file per PDF, maintaining folder structure.
    Uses parallel processing for both domains and files within domains.

    Args:
        input_dir (str): Path to pdf_combined directory
        output_dir (str): Path where markdown files should be saved
        excel_path (str, optional): Path to Excel file with URL column to filter domains
        mappings_path (str, optional): Path to save domain->URL mappings JSON file
        filenames_to_remove (list): Keywords that if found in filename, file is skipped
        max_domain_workers (int, optional): Max parallel domains. If None, uses CPU count.
        max_file_workers (int, optional): Max parallel files per domain. If None, uses CPU count.

    Returns:
        dict: Summary with 'domains_processed', 'files_converted', 'files_skipped'
    """
    print("=" * 70)
    print("PDF to Markdown Converter (Parallelized)")
    print("=" * 70)
    print(f"Input:  {input_dir}")
    print(f"Output: {output_dir}")
    if excel_path:
        print(f"Excel:  {excel_path}")
    print("=" * 70)

    # Load allowed domains from Excel if provided
    allowed_domains = None
    if excel_path:
        allowed_domains = load_allowed_domains(excel_path)

    # Load full URLs for mapping if needed
    domain_mappings = {}
    if mappings_path and excel_path:
        df = pd.read_excel(excel_path)
        df = df.fillna("")
        urls = list(df["URL"])

        for url in urls:
            if url != "":
                base_site = get_base_site_from_url(url)
                if base_site not in domain_mappings:
                    domain_mappings[base_site] = get_base_url_from_url(url)

        # Save mappings
        mappings_path_obj = Path(mappings_path)
        mappings_path_obj.parent.mkdir(parents=True, exist_ok=True)
        with open(mappings_path, 'w', encoding='utf-8') as f:
            json.dump(domain_mappings, f, indent=2)
        print(f"Saved domain mappings to {mappings_path}")

    # Process files
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # Walk through all domain folders in pdf_combined
    domain_folders = [d for d in input_path.iterdir() if d.is_dir()]

    # Filter domains if allowed_domains is provided
    if allowed_domains is not None:
        domain_folders = [d for d in domain_folders if d.name in allowed_domains]

    print(f"\nProcessing {len(domain_folders)} domain folders in parallel...")
    print("=" * 70)

    # OPTIMIZATION 4: Batch directory creation
    # Pre-create all output directories for domains
    print("Pre-creating output directories...")
    for domain_folder in domain_folders:
        domain_output_dir = output_path / domain_folder.name
        domain_output_dir.mkdir(parents=True, exist_ok=True)

        # Also create subdirectories based on input structure
        for subdir in domain_folder.rglob('*'):
            if subdir.is_dir():
                rel_path = subdir.relative_to(domain_folder)
                (domain_output_dir / rel_path).mkdir(parents=True, exist_ok=True)

    # Determine number of workers - use ThreadPoolExecutor only
    if max_file_workers is None:
        max_file_workers = min(16, mp.cpu_count())

    print(f"Processing domains sequentially with {max_file_workers} file workers per domain")
    print("  (Using ThreadPoolExecutor only to avoid process crashes)")

    results = []
    failed_domains = []

    # Process domains sequentially to avoid ProcessPoolExecutor crashes
    for domain_folder in tqdm(domain_folders, desc="Processing domains", unit="domain"):
        domain_name = domain_folder.name
        try:
            result = process_domain_parallel(
                domain_folder=domain_folder,
                input_path=input_path,
                output_path=output_path,
                allowed_domains=allowed_domains,
                filenames_to_remove=filenames_to_remove,
                max_workers=max_file_workers
            )
            results.append(result)
        except Exception as e:
            print(f"\nError processing domain {domain_name}: {e}")
            failed_domains.append(domain_name)
            results.append({'domain': domain_name, 'converted': 0, 'skipped': 0, 'failed': 0})

    # Aggregate results
    domains_processed = {r['domain'] for r in results if r['converted'] > 0 or r['skipped'] > 0 or r['failed'] > 0}
    files_converted = sum(r['converted'] for r in results)
    files_skipped = sum(r['skipped'] for r in results)
    files_failed = sum(r['failed'] for r in results)

    print("\n" + "=" * 70)
    print(f"✓ Processed {len(domains_processed)} domains")
    print(f"✓ Converted {files_converted} files")
    print(f"✓ Skipped {files_skipped} files (intentional: empty PDFs, no text, filtered keywords)")
    print(f"⚠ Failed {files_failed} files (PyMuPDF errors, corrupted PDFs)")
    if failed_domains:
        print(f"⚠ Failed {len(failed_domains)} entire domains: {', '.join(failed_domains[:5])}")
        if len(failed_domains) > 5:
            print(f"  ... and {len(failed_domains) - 5} more")
    print(f"✓ Output directory: {output_dir}")
    print("=" * 70)

    return {
        'domains_processed': len(domains_processed),
        'files_converted': files_converted,
        'files_skipped': files_skipped,
        'files_failed': files_failed,
        'domains': sorted(list(domains_processed))
    }


def main():
    """Main function with default paths."""
    input_dir = "output/pdf_combined/19945"
    output_dir = "output/markdown_pdf/19945"
    excel_path = "data/2025-11-20_19945_topics.xlsx"
    mappings_path = "output/mappings/19945/pdf_domain_mappings.json"

    convert_pdf_combined_to_markdown(
        input_dir,
        output_dir,
        excel_path=excel_path,
        mappings_path=mappings_path
    )


if __name__ == "__main__":
    main()