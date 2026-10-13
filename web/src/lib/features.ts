/**
 * Feature flags. Statements need the /v1/statements API, which lives on the staging branch;
 * the screen stays hidden until that API reaches main and the flag is turned on.
 */
export const features = {
  statements: import.meta.env.VITE_FEATURE_STATEMENTS === "true",
} as const;
