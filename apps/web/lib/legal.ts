/**
 * Facts stated on the public /privacy and /terms pages. Whoever runs a deployment
 * under another name changes them here; the wording of the pages follows.
 */
export const LEGAL = {
  appName: "Phylo Framework",
  operator: "Kiana Hashemi",
  contactEmail: "kianahashemi8@gmail.com",
  /** Change this whenever the wording of either page changes. */
  effectiveDate: "November 16, 2026",
  /** Must equal RESULT_RETENTION_DAYS of the deployment. */
  resultRetentionDays: 60,
  /** Must equal DATASET_RETENTION_DAYS of the deployment. */
  datasetRetentionDays: 60,
  /** Must equal DATASET_EXPIRATION_WARNING_HOURS of the deployment. Not a fixed 24. */
  datasetWarningHours: 24,
  /** Days within which the operator promises to answer a data request. */
  requestResponseDays: 30,
} as const;
