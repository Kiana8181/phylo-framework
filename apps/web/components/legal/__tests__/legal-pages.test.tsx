// @vitest-environment jsdom
import fs from 'node:fs';
import path from 'node:path';
import {cleanup, render, screen, within} from '@testing-library/react';
import {afterEach, describe, expect, it} from 'vitest';
import {SiteFooter} from '@/components/layout/SiteFooter';
import {PrivacyDoc} from '@/components/legal/PrivacyDoc';
import {TermsDoc} from '@/components/legal/TermsDoc';
import {METHOD_IDS} from '@/features/docs/types';
import {LEGAL} from '@/lib/legal';

afterEach(cleanup);

describe('privacy policy', () => {
  it('states what Google requires a policy for Google sign-in to disclose', () => {
    render(<PrivacyDoc />);
    for (const heading of [
      'Google user data',
      'Data we collect and how long we keep it',
      'How we use data',
      'How we share data',
      'How we protect data',
      'Your choices and rights',
    ]) {
      expect(screen.getByRole('heading', {level: 2, name: new RegExp(heading)})).toBeTruthy();
    }
    const userDataPolicy = screen.getByRole('link', {name: 'Google API Services User Data Policy'});
    expect(userDataPolicy.getAttribute('href')).toBe('https://developers.google.com/terms/api-services-user-data-policy');
    expect(document.body.textContent).toContain('Limited Use requirements');
  });

  it('names who runs the service and how to reach them', () => {
    render(<PrivacyDoc />);
    expect(document.body.textContent).toContain(LEGAL.operator);
    const contacts = screen.getAllByRole('link', {name: LEGAL.contactEmail});
    expect(contacts[0].getAttribute('href')).toBe(`mailto:${LEGAL.contactEmail}`);
  });

  it('promises the retention period the application is configured with', () => {
    const example = fs.readFileSync(path.resolve(__dirname, '../../../../../.env.example'), 'utf8');
    expect(example).toMatch(new RegExp(`^RESULT_RETENTION_DAYS=${LEGAL.resultRetentionDays}$`, 'm'));
    expect(example).toMatch(new RegExp(`^DATASET_RETENTION_DAYS=${LEGAL.datasetRetentionDays}$`, 'm'));
    expect(example).toMatch(new RegExp(`^DATASET_EXPIRATION_WARNING_HOURS=${LEGAL.datasetWarningHours}$`, 'm'));
  });
});

describe('terms of service', () => {
  it('states the research-only limit and links back to the privacy policy', () => {
    render(<TermsDoc />);
    expect(screen.getByRole('heading', {level: 2, name: /Research use only/})).toBeTruthy();
    expect(screen.getAllByRole('link', {name: 'Privacy Policy'}).map((a) => a.getAttribute('href'))).toContain('/privacy');
  });
});

describe('site footer', () => {
  it('links both documents, as Google requires of the homepage', () => {
    render(<SiteFooter />);
    const footer = within(screen.getByRole('contentinfo'));
    expect(footer.getByRole('link', {name: 'Privacy Policy'}).getAttribute('href')).toBe('/privacy');
    expect(footer.getByRole('link', {name: 'Terms of Service'}).getAttribute('href')).toBe('/terms');
  });

  it('links every method, the contact address and the public source', () => {
    render(<SiteFooter />);
    const methods = within(screen.getByRole('navigation', {name: 'Methods'})).getAllByRole('link');
    expect(methods.map((a) => a.getAttribute('href'))).toEqual(METHOD_IDS.map((id) => `/documents/${id}`));
    const footer = within(screen.getByRole('contentinfo'));
    expect(footer.getByRole('link', {name: 'Contact'}).getAttribute('href')).toBe(`mailto:${LEGAL.contactEmail}`);
    expect(footer.getByRole('link', {name: 'Source code'}).getAttribute('href')).toBe('https://github.com/Kiana8181/phylo-framework');
  });
});
