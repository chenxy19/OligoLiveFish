# OligoLiveFish
Automatic pipeline for OligoLiveFish data analysis starting from raw images, performing nuclear segmentation, drift correction, real DNA trajectory extraction and noise filtering, cross-channel matching, and filtering of low-quality tracks. Along with nuclear feature extraction, calculation of loci-to-nuclear membrane distance.

Trajectory-to-feature modeling workflows are in `trajectory_to_nuclear_features/`,
including traditional ML baselines, deep-learning experiments, and the small
derived CSV data needed to rerun them.
