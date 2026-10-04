import { expect, it } from 'vitest';
import { readDowserResult, readTreeTipColorStats, readTreeTipSizeBy } from '../src/index';

it.each([null, undefined, 'bad'])('handles missing/malformed stats %s', stats => {
  expect(readTreeTipSizeBy(stats as any)).toBeUndefined();
  expect(readTreeTipColorStats(stats as any)).toEqual({unknownValue: 'unknown'});
  expect(readDowserResult(stats as any).isDowser).toBe(false);
});
it.each([{}, {tip_size_by: ''}, {tip_size_by: 3}])('rejects invalid tip size field %j', stats => {
  expect(readTreeTipSizeBy(stats)).toBeUndefined();
});
it('reads valid plot settings and capped trait colors', () => {
  expect(readTreeTipSizeBy({tip_size_by: 'abundance'})).toBe('abundance');
  expect(readTreeTipColorStats({tip_color_by: 'isotype', unknown_value: 'NA'})).toEqual({colorBy: 'isotype', unknownValue: 'NA'});
  expect(readTreeTipColorStats({tip_states_capped: true})).toEqual({unknownValue: 'unknown'});
  expect(readTreeTipColorStats({tip_states_capped: true, unknown_value: 'NA'})).toEqual({unknownValue: 'NA'});
  expect(readTreeTipColorStats({tip_color_by: ''}).colorBy).toBeUndefined();
  expect(readTreeTipColorStats({}).colorBy).toBeUndefined();
});
it('normalizes legacy count arrays and preserves explicit zero counts', () => {
  const input_qc = {n_rows_original: 10, n_rows_after_trait_exclusion: 8, n_clones_original: 2,
    n_clones_after_trait_exclusion: 1, excluded_missing_trait: ['a', 'b'], length_mismatch: [],
    duplicate_sequence_ids: ['a'], n_missing_sequence_alignment: 0, n_missing_germline_alignment: 1};
  expect(readDowserResult({input_qc}).inputQc).toEqual({n_input_rows: 10, n_working_rows: 8,
    n_clones_input: 2, n_clones_working: 1, n_excluded_trait_missing: 2, n_length_mismatch: 0,
    n_duplicate_sequence_id: 1, n_missing_sequence_alignment: 0, n_missing_germline_alignment: 1});
  const canonical = Object.fromEntries(Object.keys(readDowserResult({input_qc}).inputQc!).map(k => [k, 0]));
  expect(readDowserResult({input_qc: canonical}).inputQc).toEqual(canonical);
});
it.each([{}, {input_qc: {}}, {input_qc: {n_input_rows: NaN}}, {input_qc: 'bad'}])('does not fabricate QC %j', value => {
  expect(readDowserResult(value).inputQc).toBeUndefined();
});
it('uses derived row count when trait filtering did not run', () => {
  expect(readDowserResult({input_qc: {n_rows_after_derived_fields: 4}}).inputQc?.n_working_rows).toBe(4);
});
it.each([{analysis_mode: 'tree_only'}, {tree_build: 'pratchet'}])('recognizes Dowser stats %j', stats => {
  expect(readDowserResult({stats}).isDowser).toBe(true);
});
it('preserves scientific tables and artifacts', () => {
  const payload = {trees_detail: [], discrete_trait_analysis: {switches: []}, time_evolution: {},
    igphyml: {}, chain_qc: {}, data_provenance: {seed: 42}, artifacts: [{kind: 'newick'}]};
  const parsed = readDowserResult(payload);
  expect(parsed.isDowser).toBe(true);
  expect(parsed.dta).toEqual(payload.discrete_trait_analysis);
  expect(parsed.timeEvolution).toEqual({});
  expect(parsed.igphyml).toEqual({});
  expect(parsed.chainQc).toEqual({});
  expect(parsed.dataProvenance).toEqual({seed: 42});
  expect(parsed.artifacts).toEqual(payload.artifacts);
  expect(readDowserResult({discrete_trait_analysis: {}}).isDowser).toBe(true);
});
