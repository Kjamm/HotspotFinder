# HotspotFinder

**English** · [한국어](README_KO.md)

HotspotFinder identifies protein–protein interfaces in a PDB complex and compares how different local tools predict the effect of replacing each interface residue with alanine. Use the residue heatmap, sequence and 3D structure to inspect candidates and see where the tools agree. Use the **한국어 / English** buttons in the top bar to switch the interface language. The browser remembers your choice.

## Quick start

Download the repository and run the following command from its root directory. A fresh checkout needs Python 3 with `venv` and `pip`, Node.js with npm, and an internet connection to download dependencies.

```sh
python3 scripts/launch.py
```

The launcher installs Python dependencies in the project's `.venv/` and builds the web interface on first use. Open the [local app](http://127.0.0.1:8765/) in your browser. Press Ctrl+C in the launch terminal to stop it.

| Platform | Launch method |
| --- | --- |
| macOS | Run the command above or double-click [HotspotFinder.command](HotspotFinder.command). |
| Linux | Run the command in a Linux terminal and install engine binaries for your CPU architecture. |
| Windows | Run the command in an Ubuntu terminal under WSL2. Install the Linux engines inside WSL2 and open the app in your Windows browser. |

End-to-end platform verification currently covers macOS on Apple Silicon. Linux and WSL2 have launch paths but still await end-to-end verification.

## Install calculation engines

Open **계산 엔진** (Calculation engines) and install the tools you want to use. The app enables each engine after a local test calculation succeeds. The jobs screen shows progress and logs and provides controls to cancel or retry a job.

| Engine | Installation | Score for a single alanine substitution |
| --- | --- | --- |
| EvoEF 1.1 | Compile the pinned source from the app | Difference in `ComputeBinding` scores between paired mutant and wild-type structures, in native EvoEF units |
| FoldX | Select the official archive for your platform | Difference in `AnalyseComplex` interaction energies for the selected partners, in kcal/mol |
| Flex ddG | Select a Rosetta archive with the executable and database | Change in the bound–unbound score difference between mutant and wild type, in Rosetta energy units (REU) |
| SAAMBE-3D | Install the isolated CPU environment and regression model | Structure-based prediction of binding ΔΔG, in kcal/mol |
| BudeAlaScan | Connect Docker and a locally prepared image | Scan score in kJ/mol, also displayed in kcal/mol after division by 4.184 |

End-to-end engine verification is pending for Flex ddG and BudeAlaScan.

EvoEF needs Git and a C++ compiler. On macOS, install Xcode Command Line Tools. On Ubuntu or WSL2, install Git and `build-essential`. The installer can reuse a matching local source checkout. [Pinned source versions](third_party/sources.json)

For FoldX and Rosetta, obtain an archive from the provider under the applicable terms. The app accepts archives up to 8 GiB compressed and 20 GiB extracted. Use the advanced settings to connect an existing installation or a larger distribution. [FoldX distribution](https://foldxsuite.crg.eu/licensing-and-services) · [Rosetta downloads](https://rosettacommons.org/software/download/)

For BudeAlaScan, prepare a local Docker image with its dependencies, including SCWRL, and the entry point `/root/bin/budeAlaScan.py`. Enter its local `sha256` image ID in the advanced settings. The app runs the test container with networking disabled. [BAlaS installation instructions](https://github.com/wells-wood-research/BAlaS)

## Analyze a complex

1. Load a PDB file or choose **예제 불러오기** to open the bundled [1JTG example](examples/1JTG_AB.pdb).
2. Choose a model, the two binding partners, the chains to scan and an interface distance cutoff.
3. Review the interface residues, select the residues and engines, and start the calculation.
4. Select a residue in the default heatmap to inspect it in the sequence and 3D viewer. Switch to the table for a numerical view.
5. Optionally run Flex ddG on selected candidates for a follow-up analysis.
6. Export a CSV or a ZIP containing the original and normalized structures, residue mapping, settings, logs and file hashes.

### Interface definition and residue mapping

The default interface cutoff is **5 Å** (configurable from 2 to 12 Å). A residue on a scan chain belongs to the interface if any of its heavy atoms falls within the cutoff of a heavy atom on the opposite partner. The distance column reports the closest qualifying pair. Eligible interface residues are selected by default.

For residues with alternate locations, the app selects the conformer with the highest summed occupancy and retains shared atoms. The engine input uses normalized chain IDs and residue numbers. The mapping records the original model, chain, residue number and insertion code and preserves numbering gaps. Alanine is excluded from scanning and glycine is optional. Unsupported cofactors, nonstandard residues or missing backbone atoms in the selected partners require structure preparation.

### Score direction and consensus

A positive score indicates predicted weakening of binding upon alanine substitution. Each engine has its own threshold and supporting evidence. A residue qualifies for consensus when at least two engines have completed scores with applicable thresholds and at least two thirds of those engines meet or exceed their respective thresholds. Thresholds start empty.

## Compare with SAAMBE-3D

In **계산 엔진**, choose **SAAMBE-3D → 자동 설치 및 검증**. The first installation needs internet access, Git and a C/C++ compiler. The installer uses an available Conda or micromamba installation. If neither is present, it downloads micromamba for the platform and verifies the archive hash.

Choose one chain per binding partner. SAAMBE-3D processes the selected residues as a single batch with one repeat. The app passes experimental conditions from the original PDB remarks to the regression model, which applies its own defaults for missing fields. [Official model and usage](https://github.com/delphi001/SAAMBE-3D/tree/182a2746c8adb7434f1ac28c111e6b3f031c59e7)

## Interpret results

Under **결과 해석** (Results analysis), every engine with completed results is selected by default. Use the checkboxes to change the comparison. The statistics use residues with all planned repeats completed under the latest settings for every selected engine. Expand the exclusion summary to see which results were left out and why.

- **Score agreement.** The scatterplot shows each engine's scores in its own units. Spearman's ρ summarizes rank agreement on shared residues. Selecting three or more engines also displays a correlation matrix.
- **Top candidates.** Set the number of candidates (*K*) to see the shared residues and the Jaccard index (intersection size divided by union size). All ties at the cutoff are included.
- **Residue ranking.** The app ranks residues by descending score within each engine and averages the ranks with equal weight. Filter by rank spread or disagreement in sign, then select a residue to inspect its structure and scores.
- **Threshold sensitivity.** Enter a positive threshold to preview which residues meet or exceed it. To use the threshold for consensus, enter the supporting evidence and save it.
- **Comparison CSV.** Each row contains the original residue identity, engine, score, unit, rank, repeat count, standard deviation and a fingerprint identifying the calculation settings.

## Job execution and reproducibility

Analyses, jobs and managed installations are stored under `.hotspotfinder/`. Set `HOTSPOT_DATA` to use another directory. After installation, calculations, the bundled Mol* viewer and exports work locally. Jobs continue when the browser is refreshed or closed. Shutting down the app interrupts active jobs. After an abnormal shutdown, interrupted jobs are marked as failed and can be retried. The default concurrency is one job.

The FastAPI service and a separate worker share a local SQLite job queue. For each residue and engine, results aggregate successful repeats from the latest applicable configuration and repeat plan. A retry replaces the earlier attempt for the same repeat. The app reports the mean and, for two or more successful repeats, the sample standard deviation.

To trace an exported score, find the residue in `residue_mapping.csv`, then inspect the corresponding `jobs/<job-id>/result.json` in the ZIP. It records the engine configuration and fingerprint, normalized input hash, repeat number and raw output values. Use `file_hashes.json` to check the SHA-256 hashes of the archived job files.

## Development checks

Run the automated tests after the launcher has prepared the Python environment.

```sh
.venv/bin/pytest -q
```

With the app running, the following command installs EvoEF, runs an example through the app, compares its scores with direct engine output and checks the export.

```sh
.venv/bin/python scripts/smoke_local.py --install
```

[Product requirements and scientific references (Korean)](docs/PRODUCT_SPEC.md)
