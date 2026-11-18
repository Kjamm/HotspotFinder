import { useLanguage } from "./i18n";
import { useEffect, useRef, useState } from "react";
import { Viewer } from "molstar/lib/apps/viewer/app";
import { MolScriptBuilder as MS } from "molstar/lib/mol-script/language/builder";
import { Script } from "molstar/lib/mol-script/script";
import {
  StructureElement,
  StructureSelection,
  StructureProperties,
} from "molstar/lib/mol-model/structure";
import { Color } from "molstar/lib/mol-util/color";
import type { Residue } from "./types";

export default function StructureViewer({
  id,
  selected,
  onSelect,
  mapping,
}: {
  id: string;
  selected: Residue | null;
  onSelect: (key: string) => void;
  mapping: Residue[];
}) {
  const { t, message } = useLanguage();
  const host = useRef<HTMLDivElement>(null),
    viewer = useRef<Viewer | null>(null);
  const callback = useRef(onSelect),
    map = useRef(mapping);
  callback.current = onSelect;
  map.current = mapping;
  const [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let dead = false;
    let own: Viewer | undefined;
    let subscription: { unsubscribe: () => void } | undefined;
    setLoaded(false);
    setError("");
    (async () => {
      try {
        const v = await Viewer.create(host.current!, {
          extensions: [],
          layoutIsExpanded: false,
          layoutShowControls: false,
          layoutShowRemoteState: false,
          layoutShowSequence: false,
          layoutShowLog: false,
          layoutShowLeftPanel: false,
          viewportShowExpand: false,
          viewportShowControls: false,
          volumeStreamingDisabled: true,
        });
        own = v;
        if (dead) {
          v.plugin.dispose();
          return;
        }
        viewer.current = v;
        v.plugin.canvas3d?.setProps({
          renderer: { backgroundColor: Color(0xfafbfd) },
        });
        const response = await fetch(`/api/analyses/${id}/pdb`);
        if (!response.ok) throw Error("구조를 불러오지 못했습니다.");
        await v.loadStructureFromData(await response.text(), "pdb");
        if (dead) return;
        for (const structure of v.plugin.managers.structure.hierarchy.current
          .structures) {
          await v.plugin.managers.structure.component.updateRepresentationsTheme(
            structure.components,
            {
              color: "chain-id",
              colorParams: {
                asymId: "auth",
                palette: {
                  name: "colors",
                  params: {
                    list: {
                      kind: "set",
                      colors: [
                        Color(0x4d83b5),
                        Color(0xc69873),
                        Color(0x73a386),
                        Color(0x8a79a9),
                        Color(0xc27f8b),
                        Color(0xa5ac71),
                      ],
                    },
                  },
                },
              },
            },
          );
        }
        if (dead) return;
        subscription = v.plugin.behaviors.interaction.click.subscribe(
          (event) => {
            const loci = event.current.loci;
            if (!StructureElement.Loci.is(loci)) return;
            const loc = StructureElement.Loci.getFirstLocation(loci);
            if (!loc) return;
            const chain = StructureProperties.chain.auth_asym_id(loc),
              number = StructureProperties.residue.auth_seq_id(loc);
            const row = map.current.find(
              (r) => r.engine_chain === chain && r.engine_number === number,
            );
            if (row) callback.current(row.key);
          },
        );
        setLoaded(true);
      } catch (e) {
        if (!dead) setError(String(e));
      }
    })();
    return () => {
      dead = true;
      subscription?.unsubscribe();
      if (own) own.plugin.dispose();
      viewer.current = null;
    };
  }, [id]);
  const selectedChain = selected?.engine_chain;
  const selectedNumber = selected?.engine_number;
  useEffect(() => {
    const v = viewer.current;
    if (
      !v ||
      selectedChain === undefined ||
      selectedNumber === undefined ||
      !loaded
    )
      return;
    const data =
      v.plugin.managers.structure.hierarchy.current.structures[0]?.cell.obj
        ?.data;
    if (!data) return;
    const expr = MS.struct.generator.atomGroups({
      "chain-test": MS.core.rel.eq([
        MS.struct.atomProperty.macromolecular.auth_asym_id(),
        selectedChain,
      ]),
      "residue-test": MS.core.rel.eq([
        MS.struct.atomProperty.macromolecular.auth_seq_id(),
        selectedNumber,
      ]),
    });
    const loci = StructureSelection.toLociWithSourceUnits(
      Script.getStructureSelection(expr, data),
    );
    v.plugin.managers.interactivity.lociSelects.selectOnly({ loci });
    v.plugin.managers.camera.focusLoci(loci, { minRadius: 12 });
  }, [selectedChain, selectedNumber, loaded]);
  return (
    <div className="molecule-wrap">
      <div className="molstar-host" ref={host} />
      {error && (
        <div className="viewer-message">
          {t("3D 뷰어 오류:")} {message(error)}
          <br />
          {t("표와 서열 분석은 계속 사용할 수 있습니다.")}
        </div>
      )}
      {!loaded && !error && (
        <div className="viewer-message">{t("구조 렌더링 중…")}</div>
      )}
    </div>
  );
}
