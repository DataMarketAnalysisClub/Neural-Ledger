import type { UserProfile } from "@/contracts/outputs/user_profile";

export type ProfileTolerance = Pick<UserProfile, "declared_tolerance">;
