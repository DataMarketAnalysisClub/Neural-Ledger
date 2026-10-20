import type { MessageKey } from "@/i18n";

/**
 * The investment accounts and wallets a user may want to link, grouped by market. Only Fintual is connected today
 * (ADR-044); the rest are listed so the screen shows where linking is going, and cannot be chosen. The API accepts
 * only "fintual" (contracts/investments/link_request), so an option turns on here and there together.
 */
export type ProviderGroup = "chile" | "global" | "china" | "latam";

export interface ProviderOption {
  readonly id: string;
  readonly name: MessageKey;
  readonly group: ProviderGroup;
  readonly available: boolean;
}

export const PROVIDER_GROUPS: readonly ProviderGroup[] = ["chile", "global", "china", "latam"];

export const PROVIDERS: readonly ProviderOption[] = [
  { id: "fintual", name: "investments.providers.fintual", group: "chile", available: true },
  { id: "robinhood", name: "investments.providers.robinhood", group: "global", available: false },
  { id: "interactive_brokers", name: "investments.providers.interactiveBrokers", group: "global", available: false },
  { id: "fidelity", name: "investments.providers.fidelity", group: "global", available: false },
  { id: "schwab", name: "investments.providers.schwab", group: "global", available: false },
  { id: "vanguard", name: "investments.providers.vanguard", group: "global", available: false },
  { id: "etoro", name: "investments.providers.etoro", group: "global", available: false },
  { id: "revolut", name: "investments.providers.revolut", group: "global", available: false },
  { id: "trading212", name: "investments.providers.trading212", group: "global", available: false },
  { id: "alipay", name: "investments.providers.alipay", group: "china", available: false },
  { id: "wechat", name: "investments.providers.wechat", group: "china", available: false },
  { id: "tiantian", name: "investments.providers.tiantian", group: "china", available: false },
  { id: "eastmoney", name: "investments.providers.eastmoney", group: "china", available: false },
  { id: "tonghuashun", name: "investments.providers.tonghuashun", group: "china", available: false },
  { id: "futu", name: "investments.providers.futu", group: "china", available: false },
  { id: "tiger", name: "investments.providers.tiger", group: "china", available: false },
  { id: "jd", name: "investments.providers.jd", group: "china", available: false },
  { id: "nubank", name: "investments.providers.nubank", group: "latam", available: false },
  { id: "mercadopago", name: "investments.providers.mercadopago", group: "latam", available: false },
];
