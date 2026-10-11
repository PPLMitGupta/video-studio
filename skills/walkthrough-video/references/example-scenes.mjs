// Worked example: an excerpt of the SIMMS "District Settings" walkthrough (47 lines, two roles,
// 9:27 final).
//
// Patterns worth copying:
//   - one signed-in page per role, each with an on-screen role label
//   - page changes go in a cue's `pre` step, so the line starts once the new page is up
//   - app-specific helpers (home, open, dialogAdd) wrap the library's hands
//   - the go-live step waits for its own confirmation and retries once
//   - a final check that the story's end state really happened
import os from 'node:os';
import path from 'node:path';
// RECORDER: the absolute path of this skill's scripts/recorder.mjs (the SKILL.md gives it)
const { createRecorder } = await import('RECORDER');

const PROJECT = path.join(os.homedir(), 'VideoStudio/projects/district-settings');
const r = await createRecorder({
  project: PROJECT,
  baseURL: 'http://localhost:4210',
  playwrightFrom: path.join(os.homedir(), 'SIMMS/SIMMS'),   // any checkout of the app with Playwright installed
  brand: 'SIMMS', accent: '#c8104a',
});
const { cue, point, spot, click, type, tabOut, pick, scrollTo, navClick, sleep, note } = r;

// ---- sign-in happens before the camera starts, so the login screen is never recorded ----
async function signInAs(who) {
  return async (page, { baseURL }) => {
    await page.goto(baseURL + '/', { waitUntil: 'domcontentloaded' });
    const f = (id) => page.locator(`[data-testid="${id}"] input, input[data-testid="${id}"]`).first();
    await f('email').waitFor({ timeout: 60000 });
    await f('email').fill(`${who}@simms.local`);
    await f('password').fill('LocalSynthetic!234');          // synthetic local account
    await page.getByTestId('submit-credentials').click();
    await page.waitForURL(/\/district\//, { timeout: 60000 });
  };
}
const it = await r.role({ label: 'IT team · District Administrator', signIn: await signInAs('district.admin'), start: '/district/settings' });
const co = await r.role({ label: 'Medicaid coordinator', signIn: await signInAs('coordinator'), start: '/district/settings' });

// ---- app-specific helpers ----
const main = (page) => page.locator('main');
const home = (page) => navClick(page, main(page).getByRole('link', { name: 'District settings', exact: true }).first());
const open = (page, name) => navClick(page, main(page).getByRole('link', { name, exact: true }).first());
async function dialogAdd(page, text, button = 'Add') {
  const d = page.getByRole('dialog');
  await type(page, d.getByRole('textbox').first(), text);
  await click(page, d.getByRole('button', { name: button, exact: true }));
  await sleep(1500);
  if (await page.getByText('The request could not be completed').count()) note('add failed: ' + text);
}

// ---- intro ----
await r.camera(await r.card('District Settings', 'Product walkthrough', 'Demo environment · synthetic data only'));
await sleep(1200);
await cue('intro');

await r.camera(it);
await cue('home1', async () => {
  await spot(it, main(it).getByText('Configuration has not begun.'));
  await sleep(1800);
  await spot(it, main(it).getByRole('heading', { name: /required sections remain/ }));
});
await cue('home2', async () => {
  await scrollTo(it, 1500);                                  // layout px; the library scales it
  await spot(it, main(it).getByRole('heading', { name: 'All sections' }));
  await sleep(2200);
  await scrollTo(it, 0);
});

// ---- a form: type, leave the field (it saves on blur), show the refusal, then the fix ----
await cue('prof3', async () => {
  await type(it, it.getByRole('textbox', { name: 'Billing NPI' }), '1234567890');
  await tabOut(it);
  await spot(it, main(it).getByText(/That NPI is not valid/));
}, () => open(it, 'District profile'));                      // `pre`: the page change, silent
await cue('prof4', async () => {
  await type(it, it.getByRole('textbox', { name: 'Billing NPI' }), '1234567893', { clear: true });
  await tabOut(it);
});

// ---- several dropdowns in a row: pick() waits for each save before the next ----
await cue('src1', async () => {
  await pick(it, /^Student information Student information/, 'Infinite Campus');
  await pick(it, /^IEP and service plans IEP and service plans/, 'SpEd Forms');
}, async () => { await home(it); await open(it, 'Where student and provider data comes from'); });

// ---- a tree: add, select, add inside ----
await cue('sch1', async () => {
  await click(it, it.getByRole('button', { name: 'Add a school' }));
  await dialogAdd(it, 'Lincoln Elementary');
  await click(it, it.getByRole('button', { name: 'Select Lincoln Elementary' }));
  await click(it, it.getByRole('button', { name: 'Add a building' }));
  await dialogAdd(it, 'Main Building');
}, async () => { await home(it); await open(it, 'Schools, buildings and locations'); });

// ---- switching role: load the other page first, then cut to it (the cut cross-fades) ----
await co.goto('http://localhost:4210/district/settings', { waitUntil: 'networkidle' }); await sleep(1200);
await r.camera(co);
await cue('co1', async () => {
  await scrollTo(co, 4000);
  await spot(co, main(co).getByRole('heading', { name: /Changes the IT team made/ }));
});

// ---- a step that must really happen: wait for its confirmation, retry once ----
await co.goto('http://localhost:4210/district/settings/go-live', { waitUntil: 'networkidle' }); await sleep(1200);
await r.camera(co);
await cue('gl1', async () => {
  await click(co, co.getByRole('button', { name: 'Give your sign-off' }));
  const done = co.getByRole('heading', { name: 'Signed off and ready to activate' });
  try { await done.waitFor({ timeout: 10000 }); }
  catch { note('sign-off retried'); await co.reload({ waitUntil: 'networkidle' }); await click(co, co.getByRole('button', { name: 'Give your sign-off' })); }
  await spot(co, done);
});

// ---- outro, and a check that the story's end state is real ----
const live = await it.goto('http://localhost:4210/district/settings/go-live', { waitUntil: 'networkidle' })
  .then(() => it.getByRole('heading', { name: 'The district is live' }).count());
if (!live) note('END STATE MISSING: district not live');
await r.camera(await r.card('District Settings', 'Two roles · every mistake caught early · every change on record', 'Demo environment · synthetic data only'));
await cue('outro');
await r.finish();
