"""Exact reproductions of meta review 1 failures."""

from dataclasses import replace

import pytest
from test_quote_library import double, library, ready

from opulse.atoms import kernel
from opulse.atoms import nodes as n
from opulse.atoms.library import exhaustive
from opulse.atoms.spec import Contract, Evidence
from opulse.atoms.values import Bottom, Card, Ok
from opulse.meta import code as c
from opulse.meta import engine
from opulse.meta import gen_code as g
from opulse.meta import notation as t
from opulse.meta.identity import Ledger, LedgerError


def test_m_code_1_given_colliding_with_canonical_local():
    program = c.make_code('operation', c.sig_op((), ('int', 'bottom')), (),
                          n.Let('tmp', n.Lit(4), n.Call('v0', ())),
                          lambda name: c.Resolved(digest='valid') if name == 'v0' else None)
    assert c.canonicalize(program) == program
    atom = kernel.Atom('v0', 0, lambda: 99)
    foreign = kernel.DictScope((atom, engine.eval_atom((atom,), {'v0': 'changed'})))
    assert engine.call('eval', (program, c.lst()), foreign).outcome == Bottom('foreign_code')
    assert engine.call('eval', (c.canonicalize(program), c.lst()), foreign).outcome == Bottom('foreign_code')


def test_m_code_2_blocks_initializers_use_previous_bindings():
    signature = c.sig_op((('int', 'bottom'),), ('int', 'bottom'))
    programs = []
    for variable in ('x', 'other'):
        body = n.Blocks(((variable, n.Var('x')),), 'start',
                        (('start', n.Block((), n.Halt(n.Var(variable)))),))
        direct = kernel.call('direct', (7,), kernel.DictScope(defns=(kernel.Defn('direct', ('x',), body),)))
        program = c.make_code('operation', signature, ('x',), body, lambda _: None)
        quoted = engine.call('eval', (program, c.lst((7,))), g.scope())
        assert direct.outcome == quoted.outcome == Ok(7)
        assert direct.steps == quoted.steps == 0
        programs.append(program)
    assert programs[0] == programs[1]


def test_m_code_2_unbound_initializer_rejected_without_exception():
    body = n.Blocks((('x', n.Var('x')),), 'start',
                    (('start', n.Block((), n.Halt(n.Var('x')))),))
    program = c.make_code('operation', c.sig_op((), ('int', 'bottom')), (), body, lambda _: None)
    assert engine.call('eval', (program, c.lst()), g.scope()).outcome == Bottom('ill_formed')


def test_m_code_3_hash_prefixed_given_atom():
    name = '#given'
    assert kernel.call(name, (), kernel.DictScope((kernel.Atom(name, 0, lambda: 8),))).outcome == Ok(8)
    program = c.make_code('operation', c.sig_op((), ('int', 'bottom')), (), n.Call(name, ()),
                          lambda _: c.Resolved(digest='my-given'))
    assert c.items(program.fields[3]) == (Card('atom', 'atom', (name, 'my-given')),)
    assert c.items(program.fields[4]) == () and c.canonicalize(program) == program


def test_m_engine_1_foreign_dependency_and_extraneous_dependency():
    signature = c.sig_op((), ('int', 'bottom'))
    foreign = c.make_code('operation', signature, (), n.Call('add', (n.Lit(2), n.Lit(3))),
                          lambda _: c.Resolved(digest='wrong'))
    root = Card('code', 'def', ('operation', signature,
                c.encode_node(n.Call('#' + c.code_hash(foreign), ())),
                c.lst((Card('atom', 'atom', ('add', g.DIGESTS['add'])),)), c.lst((foreign,))))
    assert not c.is_canonical(root)
    assert engine.call('eval', (root, c.lst()), g.scope()).outcome == Bottom('ill_formed')
    valid = c.make_code('operation', signature, (), n.Lit(3), lambda _: None)
    extra = Card('code', 'def', (*valid.fields[:4], c.lst((foreign,))))
    assert not c.is_canonical(extra)
    assert engine.call('eval', (extra, c.lst()), g.scope()).outcome == Bottom('ill_formed')
    valid_root = c.make_code('operation', signature, (), n.Call('dep', ()),
                             lambda name: c.Resolved(code=foreign) if name == 'dep' else None)
    assert c.is_canonical(valid_root)
    assert engine.call('eval', (valid_root, c.lst()), g.scope()).outcome == Bottom('foreign_code')


def test_m_engine_2_signature_fields_are_validated():
    signature = Card('sig', 'op', (c.lst((99,)), Card('edge', 'edge', ('int', 'bottom'))))
    bad = Card('code', 'def', ('operation', signature, c.encode_node(n.Lit(3)), c.lst(), c.lst()))
    assert not c.is_canonical(bad)
    assert engine.call('eval', (bad, c.lst((4,))), g.scope()).outcome == Bottom('ill_formed')


def test_m_engine_3_arity_before_body_decode():
    signature = c.sig_op((('int', 'bottom'),), ('int', 'bottom'))
    bad = Card('code', 'def', ('operation', signature, Card('expr', 'nonsense'), c.lst(), c.lst()))
    assert engine.call('run', (bad, c.lst(), 1), g.scope()).outcome == Bottom('arity')


def test_m_identity_1_reject_library_forged_dependency_evidence():
    lib = library()
    ready(lib, double())
    lib.verify('double', replace(exhaustive((range(3),), '0..2'), reference=lambda value: value * 2))
    saved = lib.get('double')
    lib._definitions['double'] = replace(saved, evidence=replace(saved.evidence, deps_hash='forged'))
    with pytest.raises(LedgerError, match='dependency hash'):
        Ledger.from_library(lib)


def test_m_notation_1_quote_non_identifier_call():
    program = c.make_code('operation', c.sig_op((), ('int', 'bottom')), (),
                          n.Call('add-two', (n.Lit(1), n.Lit(2))),
                          lambda name: c.Resolved(digest='aabb') if name == 'add-two' else None)
    printed = t.show_code(program, signature=True, deps=True, exact=True)
    assert '"add-two"(1, 2)' in printed
    assert t.parse_code(printed) == program


def test_review_gaps_ambiguous_calls_and_hash_shaped_given():
    signature = c.sig_op((), ('int', 'bottom'))
    with pytest.raises(c.CodeError, match='ambiguous call name'):
        c.make_code('operation', signature, (), n.Let('add', n.Lit(10), n.Call('add', ())),
                    lambda _: c.Resolved(digest='given'))
    with pytest.raises(c.CodeError, match='hash'):
        c.make_code('operation', signature, (), n.Call('#' + 'a' * 64, ()),
                    lambda _: c.Resolved(digest='given'))


def test_review_gaps_direct_evidence_and_deserialization():
    program = c.make_code('operation', c.sig_op((), ('int', 'bottom')), (), n.Lit(1), lambda _: None)
    ledger = Ledger()
    digest = ledger.add(program, 'w')
    wrong = Evidence('bounded', {'domain': 'one', 'size': 1}, world_hash='w', deps_hash='wrong')
    with pytest.raises(LedgerError, match='dependency hash'):
        ledger.attach_evidence(digest, 'w', wrong)
    valid = replace(wrong, deps_hash=ledger.record(digest, 'w').deps_hash)
    ledger.attach_evidence(digest, 'w', valid)
    ledger.promote(digest, 'w', Contract('one'))
    serialized = ledger.to_dict()
    serialized['records'][0]['evidence'][0]['deps_hash'] = 'wrong'
    with pytest.raises(LedgerError, match='dependency hash'):
        Ledger.from_dict(serialized)
    serialized['records'][0]['evidence'][0]['deps_hash'] = valid.deps_hash
    serialized['records'][0]['deps_hash'] = 'wrong'
    with pytest.raises(LedgerError, match='dependency hash'):
        Ledger.from_dict(serialized)
    tampered = Ledger()
    tampered.add(program, 'w')
    tampered._records[digest, 'w'] = replace(tampered.record(digest, 'w'), evidence=(wrong,))
    with pytest.raises(LedgerError, match='dependency hash'):
        tampered.promote(digest, 'w', Contract('forged'))


def test_review_gaps_generated_name_collisions_and_exact_steps():
    signature = c.sig_op((('int', 'bottom'),), ('int', 'bottom'))
    with pytest.raises(c.CodeError, match='ambiguous global and lexical name'):
        c.make_code('operation', signature, ('input',), n.Call('x0', ()),
                    lambda name: c.Resolved(digest='given') if name == 'x0' else None)
    for atom_name, body in (
            ('r0', n.Rec('loop', ('value',), n.Call('r0', ()), (n.Lit(1),), 'fuel')),
            ('v0', n.Let('value', n.Lit(2), n.Call('v0', ())))):
        program = c.make_code('operation', signature, ('input',), body,
                              lambda name, atom_name=atom_name: c.Resolved(digest='given')
                              if name == atom_name else None)
        assert c.is_canonical(program) and c.canonicalize(program) == program
        given = kernel.Atom(atom_name, 0, lambda: 17)
        scope = kernel.DictScope((given, engine.eval_atom((given,), {atom_name: 'given'})))
        direct = kernel.call('direct', (5,), kernel.DictScope(
            (given,), (kernel.Defn('direct', ('input',), body),)))
        quoted = engine.call('eval', (program, c.lst((5,))), scope)
        assert direct.outcome == quoted.outcome == Ok(17)
        assert direct.steps == quoted.steps == 1


def test_review_gaps_local_rec_shadows_given_atom():
    signature = c.sig_op((), ('int', 'bottom'))
    body = n.Rec('r0', (), n.Case(((n.Test(n.Lit(True)), n.Lit(3)),), n.Call('r0', ())),
                 (), 'fuel')
    program = c.make_code('operation', signature, (), body,
                          lambda _: c.Resolved(digest='given'))
    assert c.is_canonical(program) and c.canonicalize(program) == program
    assert c.items(program.fields[3]) == ()


def test_review_gaps_dependency_atom_conflicting_with_local_call():
    signature = c.sig_op((), ('int', 'bottom'))
    dependency = c.make_code('operation', signature, (), n.Call('v0', ()),
                             lambda name: c.Resolved(digest='given') if name == 'v0' else None)
    body = n.Let('item', n.Lit(kernel.FnRef('dep')),
                 n.Case(((n.Test(n.Lit(False)), n.Call('dep', ())),), n.Call('item', ())))
    with pytest.raises(c.CodeError, match='ambiguous (call|global)'):
        c.make_code('operation', signature, (), body,
                    lambda name: c.Resolved(code=dependency) if name == 'dep' else None)


def test_review_gaps_signature_sort_and_preflight_priority():
    signature = c.sig_op((('int', 'bottom'),), ('int', 'bottom'))
    for bad_signature in (
            Card('sig', 'op', (c.lst((Card('edge', 'edge', ('int', 'invalid')),)),
                                Card('edge', 'edge', ('int', 'bottom')))),
            Card('sig', 'op', (c.lst((Card('edge', 'edge', (1, 'bottom')),)),
                                Card('edge', 'edge', ('int', 'bottom')))),
            Card('sig', 'comb', (True, c.lst()))):
        kind = 'combinator' if bad_signature.tag == 'comb' else 'operation'
        bad = Card('code', 'def', (kind, bad_signature, c.encode_node(n.Lit(3)), c.lst(), c.lst()))
        assert not c.is_canonical(bad)
        assert engine.call('eval', (bad, c.lst()), g.scope()).outcome == Bottom('ill_formed')
    malformed = Card('code', 'def', ('operation', signature, Card('expr', 'nonsense'), c.lst(), c.lst()))
    assert engine.call('eval', (malformed, c.lst((4,))), g.scope()).outcome == Bottom('ill_formed')


def test_review_gaps_foreign_precedes_not_callable_with_digests():
    signature = c.sig_obs(())
    program = c.make_code('observation', signature, (), n.Call('add', ()),
                          lambda _: c.Resolved(digest='wrong'))
    assert c.is_canonical(program)
    assert engine.call('eval', (program, c.lst()), g.scope()).outcome == Bottom('foreign_code')


@pytest.mark.parametrize('name', ['add-two', '#given', 'two words', 'quoted"name'])
def test_review_gaps_exact_nonidentifier_names(name):
    program = c.make_code('operation', c.sig_op((), ('int', 'bottom')), (), n.Call(name, ()),
                          lambda _: c.Resolved(digest='given'))
    assert t.parse_code(t.show_code(program, signature=True, deps=True, exact=True)) == program
