import { describe, expect, it } from 'vitest';
import i18n from './index';

describe('i18n smoke tests', () => {
  it('t() returns English by default', () => {
    // app.nav.review is NOT overridden in test setup's 'en' bundle
    // Only auth, app.error, and app.loading are overlaid from zh.json.
    expect(i18n.t('app.nav.review')).toBe('Review & Audit');
  });

  it('i18n can switch to Chinese', async () => {
    await i18n.changeLanguage('zh');
    expect(i18n.t('app.nav.review')).toBe('审查与审计');
    // Reset back to English so other tests are not affected
    await i18n.changeLanguage('en');
  });
});
