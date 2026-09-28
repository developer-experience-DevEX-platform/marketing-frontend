import { getApiBaseUrl } from './config';
import { greet } from './greet';
import { Button } from './ui/Button';
import { Page } from './ui/Page';

export function App() {
  const apiBaseUrl = getApiBaseUrl();

  return (
    <Page title={greet('marketing-frontend')}>
      <p>{'Marketing site published through S3 and CloudFront'}</p>
      <p>
        API base URL:{' '}
        <span>{apiBaseUrl === '' ? 'not configured' : apiBaseUrl}</span>
      </p>
      <Button>Primary</Button>
    </Page>
  );
}
