// Constantes partagées du Studio de test LoRA.
// 0 = base model (LoRA off) — a useful control column; low values sweep down to it.
export const STRENGTH_CHOICES = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0];
export const DEFAULT_STRENGTHS = [0.7, 0.85, 1.0];
export const MAX_TEST_IMAGES = 24;
// Libellés des familles d'entraînement (= pipelines), pour le sélecteur de famille.
export const FAMILY_LABELS = { zimage: 'Z-Image', sdxl: 'SDXL', krea: 'Krea 2' };
