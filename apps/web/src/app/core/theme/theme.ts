import { definePreset } from '@primeuix/themes';
import Aura from '@primeuix/themes/aura';

/**
 * Serious financial-software look (SPEC §9.3): slate neutrals, primary #0f172a
 * (configurable per tenant later), no gradients.
 */
export const SayyaraPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '{slate.50}',
      100: '{slate.100}',
      200: '{slate.200}',
      300: '{slate.300}',
      400: '{slate.400}',
      500: '{slate.500}',
      600: '{slate.600}',
      700: '{slate.700}',
      800: '{slate.800}',
      900: '{slate.900}',
      950: '{slate.950}',
    },
    colorScheme: {
      light: {
        primary: {
          color: '#0f172a',
          contrastColor: '#ffffff',
          hoverColor: '{slate.800}',
          activeColor: '{slate.700}',
        },
      },
    },
  },
});
