# HotspotFinder user guide

**English** · [한국어](USER_GUIDE_KO.md) · [Project README](../README.md)

Start with the bundled 1JTG complex to learn the workflow. You can inspect the interface and explore the 3D structure as soon as the app opens. To see a predicted score, install one engine and run a calculation. To compare predictions, run a second engine on the same residues.

## 1. Launch the app

From the downloaded project directory, run the command below. The first launch needs Python 3 with `venv` and `pip`, Node.js with npm, and internet access. The launcher creates the Python environment, installs dependencies and builds the interface.

```sh
python3 scripts/launch.py
```

Leave the terminal open. If the browser does not open automatically, open the [local app](http://127.0.0.1:8765/). Choose **English** in the top bar to match the labels in this guide. The browser remembers your choice.

On macOS you can also double-click `HotspotFinder.command`. On Linux, launch from a terminal. On Windows, run the command and install engines inside Ubuntu on WSL2, then open the local app in your Windows browser. End-to-end platform testing currently covers Apple Silicon macOS.

## 2. Run your first analysis with 1JTG

1. Open **Interface analysis → Load example**. Set **Partner 1** to A, **Partner 2** to B and **Chains to scan** to A. This asks which residues on chain A contact chain B.
2. Leave the interface cutoff at **5 Å** and click **Inspect interface**. The sequence, 3D view and residue heatmap appear. At this stage the app has identified contacts. The engine columns fill when calculations finish.
3. Open **Engines → EvoEF → Install and validate**. EvoEF needs Git and a C++ compiler. Follow installation and the example calculation under **Jobs**. Continue when EvoEF shows **Ready**. If an engine is already ready, you can use it instead.
4. Reopen the example under **Recent analyses**. Eligible interface residues are initially checked. For a short first run, clear the header checkbox in **Per-residue results**, then check two or three eligible rows. Clicking a residue label focuses it in the structure. Its checkbox controls whether it will be calculated.
5. Under **Run calculations**, select EvoEF, leave **Repeats** at 1 and click **Calculate … residues**. Open **Jobs** to follow progress. Return to the analysis and click a scored residue to see the value, units and run details. With one successful repeat, the standard deviation (SD) is blank.
6. To compare another engine, select it and submit the same residues. Open **Results analysis** and check the two engines. With at least two shared, fully calculated residues, you can inspect their mean ranks.

## 3. Set up your own complex

Choose **Load PDB** or drop a `.pdb` or `.ent` file on the upload area. Use PDB format, up to 20 MB. For an mmCIF structure, export it as PDB first and check the chain identifiers after conversion.

| Control | How to choose |
| --- | --- |
| Structure model | Select the model whose coordinates you want to analyze. |
| Partner 1 / Partner 2 | Select the chains on each side of the interaction. Each group needs at least one chain and the groups must be disjoint. |
| Chains to scan | Choose which partner chains will receive alanine substitutions. To inspect the other side too, include its chains here. |
| Interface cutoff (Å) | The default is 5 Å, with 2–12 Å allowed. A residue qualifies when a heavy atom lies within this distance of a heavy atom on the opposite partner. |
| Include Gly→Ala | Off by default. Enable it if you want to include glycine substitutions, which add a side chain. Native alanine is always excluded from scanning. |

After **Inspect interface**, use **All residues / manual selection** to include eligible scan-chain residues outside the distance cutoff. Search by original PDB label, such as `A:Y105`. The header checkbox affects only the eligible rows currently displayed. Clearing a search or changing a filter can reveal additional checked residues, so review **Selected residues** before submitting.

## 4. Choose an engine and track the job

| Engine | Setup in **Engines** | Run settings and score |
| --- | --- | --- |
| EvoEF | Choose **Install and validate**. The app compiles the source locally. | Native EvoEF binding score units. |
| FoldX | Obtain the official distribution for your platform and choose **Install from archive**. | Change in interaction energy for the selected partners, in kcal/mol. |
| SAAMBE-3D | Choose **Install and validate** to prepare its CPU environment and model. First installation needs internet, Git and a compiler. | Exactly one chain per partner. Selected residues run as a batch with one repeat. Predicted binding ΔΔG in kcal/mol. |
| BudeAlaScan | In **Advanced settings**, enter the Docker executable and the local image ID for a prepared BudeAlaScan image with SCWRL. Save and run the test calculation. | One scan. The app converts the native kJ/mol score to kcal/mol for display. |
| Flex ddG | Install from a Rosetta archive containing the executable and database. | Check the residues of interest and use the separate **Flex ddG follow-up** panel. The default ensemble size is 35. Scores are in REU. |

For existing installations, enter the absolute executable path and any required data directory or image ID in advanced settings. Save and run the test calculation. **Ready** means the example input ran and its output could be read. End-to-end engine verification is still pending for Flex ddG and BudeAlaScan. [Installation details and distribution links](../README.md#install-calculation-engines)

The default is one concurrent job. Adjust **Concurrent jobs** under **Engines** or set the per-job **Time limit (s)** before submission. Selecting SAAMBE-3D locks the standard run to one repeat. For BudeAlaScan, set repeats to one. Submit other engines separately if you want multiple repeats. You can navigate away or close the browser while the local service runs. In **Jobs**, open **Log** for a failed job, resolve the reported issue and retry. Stop the app with Ctrl+C in the launch terminal after jobs finish.

## 5. Read the results

- **Heatmap and Table.** A positive score indicates predicted weaker binding after the alanine substitution. A dash means no result is available. Read each column in its own units and compare residues within that column. Switch to **Table** to read the numbers without color. A count such as `2/3` means two of three planned repeats have completed. The displayed mean uses successful repeats, with sample SD from two or more.
- **Results analysis.** Check the engines you want to compare. The comparison uses residues with all repeats complete under the latest configuration in every selected engine. Open **Cohort and exclusions** if fewer residues appear than you expected. Spearman’s ρ measures agreement in rank. The top-K overlap counts ties at the boundary, and the Jaccard index is the intersection divided by the union. A lower mean rank places a residue nearer the top across engines. A large rank spread flags disagreement worth inspecting.
- **Consensus thresholds.** After an engine produces results, enter a positive threshold in its displayed units and record the benchmark, reference or protocol that supports it. The **Threshold sensitivity** preview shows how many residues would pass. Save the threshold to apply it. In **Consensus**, the three counts mean engines supporting the call / engines assessed / engines with a run for that residue. For example, `2 / 3 / 4` meets the rule because two of three assessed engines support the residue. The rule requires at least two assessed engines and support from at least two thirds of those assessed. A blank threshold leaves the score visible and excludes that engine from the call. A consensus candidate is a prediction for experimental follow-up.

## 6. Export or revisit an analysis

| Action | What you receive |
| --- | --- |
| **Per-residue results → CSV** | `hotspots.csv`, with a row per residue and engine. Includes units, repeat counts, status and threshold support, including rows for engines without scores. |
| **Results analysis → Comparison CSV** | The current comparison of shared completed residues, including ranks, SD and configuration fingerprints. The link appears when the comparison has shared results. |
| **Per-residue results → Full archive** | A ZIP with the original and normalized PDBs, residue mapping, analysis settings, results and available job files. |

To trace a score back to the structure, find its original chain, residue number and insertion code in `residue_mapping.csv`. Read the engine chain and number on the same row, then inspect the corresponding `jobs/<job-id>/result.json`. Reopen saved analyses from **Recent analyses**. The default local data directory is `.hotspotfinder/` under the project.

## Troubleshooting

| What you see | What to check |
| --- | --- |
| The calculation button is disabled | Check at least one eligible residue and a ready engine. For SAAMBE-3D, check the one-chain-per-partner setting. |
| No interface residues appear | Clear search and filters. Check the selected model, both partners and scan chains. Review the distance cutoff and confirm the chains physically contact in that structure. |
| The app reports missing atoms or unsupported cofactors | Expand the structure preparation record and inspect the original PDB. Prepare a supported structure and load it as a new analysis. The app preserves numbering gaps and does not build missing loops. |
| A score is visible but the comparison or consensus is empty | Check for unfinished repeats, different residue sets or older engine configurations. For consensus, also check that at least two engines have applicable saved thresholds. |
