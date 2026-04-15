-- Archive any currently active poll
UPDATE poll SET status = 'archived', archived_at = NOW() WHERE status = 'active';

-- Insert the logo poll
INSERT INTO poll (title, question, options, status)
VALUES (
  'Logo Vote',
  'Which logo should Datasnoop use?',
  '["Magnifier", "Eye", "Radar"]',
  'active'
);
