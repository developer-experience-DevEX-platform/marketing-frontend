import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { App } from './App';

describe('App', () => {
  it('renders the greeting', () => {
    window.__APP_CONFIG__ = { API_BASE_URL: '' };
    render(<App />);
    expect(screen.getByRole('heading').textContent).toBe(
      'Welcome to marketing-frontend',
    );
    expect(
      screen.getByText(
        'Cache check: this copy should appear after invalidation',
      ),
    ).toBeDefined();
    expect(screen.getByText('not configured')).toBeDefined();
  });
});
