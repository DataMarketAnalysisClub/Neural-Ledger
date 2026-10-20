/* Generated from contracts/ by web/scripts/gen-contracts.mjs. Do not edit by hand. */

/**
 * data of DELETE /v1/memory/{chain_id}: every version of the chain is deleted in one transaction, pending proposals that would extend it are revoked (an old proposal cannot restore it), and one MEMORY_DELETED audit event with counts remains. Another user's chain is 404.
 */
export interface MemoryDeletion {
  chain_id: string;
  deleted_versions: number;
  revoked_proposals: number;
}
