---
title: Application of nonlinear noise regression in the Virgo detector
authors:
- Kiendrebeogo, R. Weizmann
- Saleem, Muhammed
- Bizouard, Marie Anne
- Chen, Andy H.~Y.
- Christensen, Nelson
- Chou, Chia-Jui
- Coughlin, Michael W.
- Janssens, Kamiel
- Kam, S. Zacharie
- Koulidiati, Jean
- Yeh, Shu-Wei
date: '2025-01-01T00:00:00Z'
publication_types:
- refereed
publication_years:
- '2025'
featured: true
abstract: This work presents the first demonstration of nonlinear noise regression
  in the Virgo detector using deep learning techniques. We use DeepClean, a convolutional
  autoencoder previously shown to be effective in denoising LIGO data, as our tool
  for modeling and subtracting environmental and technical noise in Virgo. The method
  uses auxiliary witness channels to learn correlated noise features and remove them
  from the strain data. For this study, we apply DeepClean to Virgo O3b data, using
  225 witness channels selected across 13 targeted frequency bands. Our analysis confirms
  the presence of nonlinear couplings in the subtracted noise, highlighting the importance
  of DeepClean-like tools in capturing such effects. We observe up to a 1.3 Mpc improvement
  in the binary neutron star inspiral range (∼2.5% gain), and an average increase
  of 1.7% in the recovered signal-to-noise ratio for injected binary black hole signals.
  Parameter estimation studies further confirm that DeepClean does not introduce bias
  in the recovery of source parameters. These results demonstrate the robustness of
  DeepClean on Virgo data and support its adoption in real-time noise subtraction
  frameworks for future observing runs.
publication:
  name: Physical Review D
  volume: '112'
  issue: '8'
  pages: 083053
  publisher: ''
hugoblox:
  ids:
    doi: 10.1103/hwnc-r7yy
    arxiv: '2410.06220'
---
