import { Translate, WarningCircle } from "@phosphor-icons/react";
import { LOCALES, locale, setLocale, t, type Locale } from "@/i18n";

/** The interface language. Choosing one reloads the page in that language (see setLocale). */
export function LanguagePicker() {
  const picker = (
    <label className="flex items-center gap-1.5 text-sm text-ink-2">
      <Translate aria-hidden className="size-4" />
      <span className="sr-only">{t("profile.language")}</span>
      <select
        value={locale}
        onChange={(e) => setLocale(e.target.value as Locale)}
        className="h-8 rounded-control border border-control bg-surface px-2 text-sm text-ink focus:outline-none focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent/25"
      >
        {Object.entries(LOCALES).map(([code, name]) => (
          <option key={code} value={code} lang={code}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
  // The Chinese strings are machine-assisted and unreviewed: say so wherever the language is chosen.
  if (locale !== "zh") return picker;
  return (
    <div className="flex flex-col items-end gap-1">
      {picker}
      <p className="m-0 flex max-w-[16rem] items-start gap-1 text-right text-xs text-ink-3">
        <WarningCircle aria-hidden className="mt-px size-3.5 shrink-0" />
        {t("profile.languageUnreviewed")}
      </p>
    </div>
  );
}
