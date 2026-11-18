import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import translations from "./en.json";

type Language = "ko" | "en";
const storageKey = "hotspotfinder.language";
const english: Record<string, string> = translations;

function interpolate(
  template: string,
  values: readonly (string | number | null)[],
) {
  return template.replace(/\{(\d+)\}/g, (token, index) =>
    String(values[Number(index)] ?? token),
  );
}

// The API also returns diagnostics embedded in saved jobs. Match only known
// message templates so paths, engine names and other dynamic values survive.
const patterns = Object.keys(english)
  .filter((key) => /\{\d+\}/.test(key))
  .map((key) => ({
    key,
    pattern: new RegExp(
      "^" +
        key
          .split(/\{\d+\}/)
          .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
          .join("([\\s\\S]*?)") +
        "$",
    ),
  }));

function translator(language: Language) {
  const t = (key: string, ...values: (string | number | null)[]) =>
    interpolate(language === "en" ? (english[key] ?? key) : key, values);
  const message = (source: string): string => {
    if (language === "ko" || !/[가-힣]/.test(source)) return source;
    if (Object.hasOwn(english, source)) return english[source];
    if (source.startsWith("Error: "))
      return "Error: " + message(source.slice(7));
    for (const { key, pattern } of patterns) {
      const match = pattern.exec(source);
      if (match) {
        const values = match.slice(1);
        if (key === "PDB를 읽을 수 없습니다: {0}")
          values[0] = message(values[0]);
        return t(key, ...values);
      }
    }
    return source;
  };
  return { language, t, message };
}

const LanguageContext = createContext<
  | (ReturnType<typeof translator> & {
      setLanguage: (language: Language) => void;
    })
  | null
>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<Language>(() => {
    try {
      return localStorage.getItem(storageKey) === "en" ? "en" : "ko";
    } catch {
      return "ko";
    }
  });
  useEffect(() => {
    document.documentElement.lang = language;
    try {
      localStorage.setItem(storageKey, language);
    } catch {
      // The controls still work when storage is disabled.
    }
  }, [language]);
  const value = useMemo(
    () => ({ ...translator(language), setLanguage }),
    [language],
  );
  return (
    <LanguageContext.Provider value={value}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const value = useContext(LanguageContext);
  if (!value) throw new Error("Missing LanguageProvider");
  return value;
}
