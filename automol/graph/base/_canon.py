""" canonicalization functions

BEFORE ADDING ANYTHING, SEE IMPORT HIERARCHY IN __init__.py!!!!

Reference:
Schneider, Sayle, Landrum. J. Chem. Inf. Model. 2015, 55, 10, 2111–2120
"""
import itertools
import functools
import numbers
from collections import abc
import numpy
from phydat import ptab
from automol import util
from automol.util import dict_
from automol.graph.base._core import atom_keys
from automol.graph.base._core import backbone_keys
from automol.graph.base._core import bond_orders
from automol.graph.base._core import atom_stereo_keys
from automol.graph.base._core import bond_stereo_keys
from automol.graph.base._core import stereo_parities
from automol.graph.base._core import atom_stereo_parities
from automol.graph.base._core import bond_stereo_parities
from automol.graph.base._core import set_atom_stereo_parities
from automol.graph.base._core import set_stereo_parities
from automol.graph.base._core import has_stereo
from automol.graph.base._core import has_atom_stereo
from automol.graph.base._core import atom_symbols
from automol.graph.base._core import mass_numbers
from automol.graph.base._core import tetrahedral_atom_keys
from automol.graph.base._core import atoms_neighbor_atom_keys
from automol.graph.base._core import atom_stereo_sorted_neighbor_keys
from automol.graph.base._core import bond_stereo_sorted_neighbor_keys
from automol.graph.base._core import atoms_bond_keys
from automol.graph.base._core import implicit
from automol.graph.base._core import explicit
from automol.graph.base._core import atom_implicit_hydrogens
from automol.graph.base._core import backbone_hydrogen_keys
from automol.graph.base._core import nonbackbone_hydrogen_keys
from automol.graph.base._core import atom_nonbackbone_hydrogen_keys
from automol.graph.base._core import relabel
from automol.graph.base._core import without_pi_bonds
from automol.graph.base._core import without_bonds_by_orders
from automol.graph.base._core import without_stereo
from automol.graph.base._core import without_dummy_atoms
from automol.graph.base._core import ts_forming_bond_keys
from automol.graph.base._core import ts_breaking_bond_keys
from automol.graph.base._core import ts_reverse
from automol.graph.base._core import is_ts_graph
from automol.graph.base._algo import is_connected
from automol.graph.base._algo import connected_components
from automol.graph.base._algo import rings_bond_keys
from automol.graph.base._kekule import rigid_planar_bond_keys
from automol.graph.base._geom import geometry_atom_parity
from automol.graph.base._geom import geometry_bond_parity


# # canonical key functions
def canonical_enantiomer(gra):
    """ Determine the canonical graph of the canonical enantiomer.

    Graphs with stereo will be reflected.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :returns: a canonicalized graph of the canonical enantiomer, along with
        a boolean flag indicating whether or not the graph has been
        reflected; `True` indicates it has been, `False` indicates it
        hasn't, and `None` indicates that it isn't an enantiomer
    :rtype: (automol graph data structure, bool)
    """
    ce_gra, _, is_refl = canonical_enantiomer_with_keys(gra)
    return ce_gra, is_refl


def canonical_enantiomer_with_keys(gra):
    """ Determine the canonical graph of the canonical enantiomer, along with
    the canonical key mapping.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :returns: a canonicalized graph of the canonical enantiomer, along with
        a boolean flag indicating whether or not the graph has been
        reflected; `True` indicates it has been, `False` indicates it
        hasn't, and `None` indicates that it isn't an enantiomer
    :rtype: (automol graph data structure, bool)
    """
    if not has_atom_stereo(gra):
        ce_gra = gra
        ce_can_key_dct = canonical_keys(gra, backbone_only=False)
        is_refl = None
    else:
        # Calculate canonical keys for the unreflected graph while converting
        # to the local stereo representation
        ugra = gra
        ucan_key_dct, uloc_gra = calculate_priorities_and_assign_stereo(
                ugra, backbone_only=False, break_ties=True,
                par_eval_=parity_evaluator_read_canonical_(),
                par_eval2_=parity_evaluator_flip_local_())

        # Reflect the graph in the local stereo representation
        rloc_gra = reflect_local_stereo(uloc_gra)

        # Determine canonical keys for the reflected graph while converting
        # back to the canonical stereo representation
        rcan_key_dct, rgra = calculate_priorities_and_assign_stereo(
                rloc_gra, backbone_only=False, break_ties=True,
                par_eval_=parity_evaluator_flip_local_(),
                par_eval2_=parity_evaluator_flip_local_())

        is_can = is_canonical_enantiomer(ugra, ucan_key_dct,
                                         rgra, rcan_key_dct)

        # The `is_refl` flag indicates whether or not the canonical enantiomer
        # is the reflected form of the input graph. Set to `None` if achiral.
        is_refl = None if is_can is None else (not is_can)

        if is_refl:
            ce_gra = rgra
            ce_can_key_dct = rcan_key_dct
        else:
            ce_gra = ugra
            ce_can_key_dct = ucan_key_dct

    return ce_gra, ce_can_key_dct, is_refl


def stereo_assignment_representation(gra, pri_dct):
    """ Generate a representation of a stereo assignment, for checking for
    symmetric equivalence or for determining a canonical enantiomer

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: A dictionary mapping atom keys to priorities
    :type pri_dct: dict
    :returns: A canonical representation of the assignment
    """
    atm_keys = sorted(atom_stereo_keys(gra), key=pri_dct.__getitem__)
    bnd_keys = sorted(bond_stereo_keys(gra),
                      key=lambda x: sorted(map(pri_dct.__getitem__, x)))

    atm_pris = tuple([pri_dct[k]] for k in atm_keys)
    bnd_pris = tuple(sorted(map(pri_dct.__getitem__, k)) for k in bnd_keys)

    atm_pars = dict_.values_by_key(atom_stereo_parities(gra), atm_keys)
    bnd_pars = dict_.values_by_key(bond_stereo_parities(gra), bnd_keys)

    pris = atm_pris + bnd_pris
    pars = atm_pars + bnd_pars
    rep = tuple(zip(pris, pars))
    return rep


def is_canonical_enantiomer(ugra, upri_dct, rgra, rpri_dct):
    """ Is this enantiomer the canonical one?

    :param ugra: An unreflected molecular graph
    :type ugra: automol graph data structure
    :param upri_dct: A dictionary mapping atom keys to priorities for `ugra`
    :type upri_dct: dict
    :param rgra: A reflected molecular graph
    :type rgra: automol graph data structure
    :param rpri_dct: A dictionary mapping atom keys to priorities for `rgra`
    :type rpri_dct: dict
    :returns: `True` if it is, `False` if it isn't, and `None` if it isn't an
        enantiomer
    """
    urep = stereo_assignment_representation(ugra, upri_dct)
    rrep = stereo_assignment_representation(rgra, rpri_dct)
    return True if (urep < rrep) else False if (urep > rrep) else None


def ts_direction_representation(tsg, pri_dct):
    """ Generate a representation of the reaction direction to determine the
    canonical direction of a TS graph

    The reaction representation consists of two pieces:

    1. Canonical representations of the forming and breaking bonds,
    respectively.
    2. Canonical representations of the stereo assignments.

    :param tsg: A TS graph
    :type tsg: automol graph data structure
    :param pri_dct: A dictionary mapping atom keys to priorities
    :type pri_dct: dict
    :returns: A canonical representation of the TS reaction
    """
    frm_keys = ts_forming_bond_keys(tsg)
    brk_keys = ts_breaking_bond_keys(tsg)
    # Rep value 1: Number of bonds broken and formed
    rxn_rep1 = (len(frm_keys), len(brk_keys))
    # Rep value 2: Canonical keys of bonds broken and formed
    rxn_rep2 = (
        sorted(sorted(map(pri_dct.__getitem__, k)) for k in frm_keys),
        sorted(sorted(map(pri_dct.__getitem__, k)) for k in brk_keys))
    # Rep value 3: Stereochemistry
    ste_rep = stereo_assignment_representation(tsg, pri_dct)
    rep = (rxn_rep1, rxn_rep2, ste_rep)
    return rep


def ts_is_canonical_direciton(ftsg, fpri_dct, rtsg, rpri_dct):
    """ Is this TS direction the canonical one?

    :param ftsg: A TS graph in the forward direction
    :type ftsg: automol graph data structure
    :param fpri_dct: A dictionary mapping atom keys to priorities for the
        forward direction
    :type fpri_dct: dict
    :param rtsg: A TS graph in the reverse direction
    :type rtsg: automol graph data structure
    :param rpri_dct: A dictionary mapping atom keys to priorities for the
        reverse direction
    :type rpri_dct: dict
    :returns: A canonical representation of the TS reaction
    """
    ftsg = implicit(ftsg)
    fpri_dct = dict_.by_key(fpri_dct, atom_keys(ftsg))
    frep = ts_direction_representation(ftsg, fpri_dct)

    rtsg = implicit(rtsg)
    rpri_dct = dict_.by_key(rpri_dct, atom_keys(rtsg))
    rrep = ts_direction_representation(rtsg, rpri_dct)
    return frep < rrep


def canonical(gra):
    """ A graph relabeled with canonical keys

    Stereo parities in the graph are assumed to be canonical.

    Requires a connected graph

    :param gra: a connected molecular graph with canonical stereo parities
    :type gra: automol graph data structure
    :returns: a new molecular graph with canonical keys; if explicit
        hydrogens are included, they will be relabeled as well
    """
    can_key_dct = canonical_keys(gra, backbone_only=False)
    return relabel(gra, can_key_dct)


def canonical_keys(gra, backbone_only=True):
    """ Determine canonical keys for this graph.

    Stereo parities in the graph are assumed to be canonical.

    Requires a connected graph

    :param gra: a connected molecular graph with canonical stereo parities
    :type gra: automol graph data structure
    :param backbone_only: Consider backbone atoms only?
    :type backbone_only: bool
    :param break_ties: Break ties after keys have been refined?
    :type break_ties: bool
    :returns: a dictionary of canonical keys by atom key
    :rtype: dict[int: int]
    """
    atm_par_dct0 = atom_stereo_parities(gra)
    bnd_par_dct0 = bond_stereo_parities(gra)

    can_key_dct, gra = calculate_priorities_and_assign_stereo(
        gra, backbone_only=backbone_only, break_ties=True)

    atm_par_dct = atom_stereo_parities(gra)
    bnd_par_dct = bond_stereo_parities(gra)

    assert atm_par_dct == atm_par_dct0, (
        f"Atom stereo parities don't match input. Something is wrong:\n"
        f"input: {atm_par_dct0}\n"
        f"return: {atm_par_dct}\n"
    )

    assert bnd_par_dct == bnd_par_dct0, (
        f"Bond stereo parities don't match input. Something is wrong:\n"
        f"input: {bnd_par_dct0}\n"
        f"return: {bnd_par_dct}\n"
    )

    return can_key_dct


# # canonical stereo functions
def stereogenic_atom_keys(gra, pri_dct=None, assigned=False):
    """ Find stereogenic atoms in this graph.

    If the `assigned` flag is set to `False`, only  unassigned stereogenic
    atoms will be detected.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :param assigned: Include atoms that already have stereo assignments?
    :param assigned: bool
    :returns: the stereogenic atom keys
    :rtype: frozenset
    """
    gra = without_dummy_atoms(gra)
    pri_dct = (canonical_priorities(gra, backbone_only=False)
               if pri_dct is None else pri_dct)
    ste_atm_keys = stereogenic_atom_keys_from_priorities(
        gra, pri_dct=pri_dct, assigned=assigned)
    return ste_atm_keys


def stereogenic_bond_keys(gra, pri_dct=None, assigned=False):
    """ Find stereogenic bonds in this graph.

    If the `assigned` flag is set to `False`, only  unassigned stereogenic
    bonds will be detected.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :param assigned: Include bonds that already have stereo assignments?
    :param assigned: bool
    :returns: the stereogenic bond keys
    :rtype: frozenset
    """
    gra = without_dummy_atoms(gra)
    pri_dct = (canonical_priorities(gra, backbone_only=False)
               if pri_dct is None else pri_dct)
    ste_bnd_keys = stereogenic_bond_keys_from_priorities(
        gra, pri_dct=pri_dct, assigned=assigned)
    return ste_bnd_keys


def stereogenic_keys(gra, pri_dct=None, assigned=False):
    """ Find stereogenic atoms and bonds in this graph.

    If the `assigned` flag is set to `False`, only  unassigned stereogenic
    atoms will be detected.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :param assigned: Include atoms/bonds that already have assignments?
    :param assigned: bool
    :returns: keys to stereogenic atoms and bonds
    :rtype: frozenset
    """
    gra = without_dummy_atoms(gra)
    pri_dct = (canonical_priorities(gra, backbone_only=False)
               if pri_dct is None else pri_dct)
    ste_keys = stereogenic_keys_from_priorities(
        gra, pri_dct, assigned=assigned)
    return ste_keys


def reflect(gra):
    """ Calculate new parities that would result from geometric reflection

    To replicate the effect of reflecting the geometry, we convert to local
    stereo, invert parities, and then convert back.

    :param gra: molecular graph with canonical stereo parities
    :type gra: automol graph data structure
    """
    if has_atom_stereo(gra):
        loc_gra = to_local_stereo(gra)
        loc_gra = reflect_local_stereo(loc_gra)
        gra = from_local_stereo(loc_gra)
    return gra


def reflect_local_stereo(gra):
    """ Reflect a graph with local stereo parities.

    Assuming local stereo parities, the parities can simply be reversed.

    :param gra: molecular graph with canonical stereo parities
    :type gra: automol graph data structure
    """
    atm_par_dct = atom_stereo_parities(gra)
    atm_par_dct = dict_.transform_values(
        atm_par_dct, lambda x: x if x is None else not x)
    gra = set_atom_stereo_parities(gra, atm_par_dct)
    return gra


def to_local_stereo(gra, pri_dct=None):
    """ Convert canonical stereo parities to local ones

    :param gra: molecular graph with canonical stereo parities
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :returns: molecular graph with local stereo parities
    :rtype: automol graph data structure
    """
    can_gra = gra
    if has_stereo(can_gra):
        pri_dct_ = (None if pri_dct is None else
                    dict_.by_key(pri_dct, backbone_keys(can_gra)))
        _, loc_gra = calculate_priorities_and_assign_stereo(
                can_gra, backbone_only=False, break_ties=False,
                par_eval_=parity_evaluator_read_canonical_(),
                par_eval2_=parity_evaluator_flip_local_(),
                pri_dct=pri_dct_)
    else:
        loc_gra = can_gra

    return loc_gra


def from_local_stereo(gra, pri_dct=None):
    """ Convert local stereo parities to canonical ones

    :param gra: molecular graph with local stereo parities
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :returns: molecular graph with canonical stereo parities
    :rtype: automol graph data structure
    """
    loc_gra = gra

    if has_stereo(loc_gra):
        pri_dct_ = (None if pri_dct is None else
                    dict_.by_key(pri_dct, backbone_keys(loc_gra)))
        _, can_gra = calculate_priorities_and_assign_stereo(
                loc_gra, backbone_only=False, break_ties=False,
                par_eval_=parity_evaluator_flip_local_(),
                par_eval2_=parity_evaluator_flip_local_(),
                pri_dct=pri_dct_)
    else:
        can_gra = loc_gra

    return can_gra


def set_stereo_from_geometry(gra, geo, geo_idx_dct=None):
    """ Determine stereo parities from a geometry

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param geo: molecular geometry
    :type geo: automol geometry data structure
    :param geo_idx_dct: If they don't already match, specify which graph
        keys correspond to which geometry indices.
    :type geo_idx_dct: dict[int: int]
    :returns: molecular graph with stereo parities set from geometry;
        parities already present will be wiped out
    :rtype: automol graph data structure
    """
    atm_keys = sorted(atom_keys(gra))
    geo_idx_dct = (geo_idx_dct if geo_idx_dct is not None
                   else {k: i for i, k in enumerate(sorted(atm_keys))})

    par_eval_ = parity_evaluator_from_geometry_(geo, geo_idx_dct=geo_idx_dct)
    _, gra = calculate_priorities_and_assign_stereo(
        gra, par_eval_=par_eval_)

    return gra


# # core algorithm functions
def canonical_priorities(gra, backbone_only=True, break_ties=False,
                         pri_dct=None):
    """ Determine canonical priorities for this graph's atoms

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param backbone_only: Consider backbone atoms only?
    :type backbone_only: bool
    :param break_ties: Break ties after priorities have been refined?
    :type break_ties: bool
    :param pri_dct: Optional initial priorities, to be refined.
    :type pri_dct: dict[int: int]
    :returns: A dictionary of canonical priorities by atom key.
    :rtype: dict[int: int]
    """
    pri_dct, _ = calculate_priorities_and_assign_stereo(
        gra, backbone_only=backbone_only, break_ties=break_ties,
        pri_dct=pri_dct)
    return pri_dct


def calculate_priorities_and_assign_stereo(
        gra, par_eval_=None, par_eval2_=None, break_ties=False,
        backbone_only=True, pri_dct=None):
    """ Determine canonical priorities and assign stereo parities to this graph

    This is how the parity evaluators are to be called:
    >>> par = par_eval_(pri_dct)(key)               # this returns the parity

    :param gra: a molecular graph
    :type gra: automol graph data structure
    :param par_eval_: A parity evaluator for assigning parities during the
        priority calculation.
    :param par_eval2_: An optional second parity evaluator for assigning
        the parities that will be returned, if different from those to be
        used for the priority calculation.
    :param break_ties: Break ties to determine canonical keys from
        canonical priorities?
    :type break_ties: bool
    :param backbone_only: Consider backbone atoms only?
    :type backbone_only: bool
    :param pri_dct: Optional initial priorities, to be refined.
    :type pri_dct: dict[int: int]
    :returns: A dictionary of canonical priorities by atom key and a graph
        with stereo assignments.
    :rtype: dict[int: int], molecular graph data structure
    """

    # Store a copy in the same format for the return. Stereo parities will be
    # added to this and returned.
    gra2 = without_stereo(gra)

    gra = without_dummy_atoms(gra)
    cgras = connected_components(gra)
    cpri_dcts = [None if pri_dct is None else dict_.by_key(pri_dct, ks)
                 for ks in map(atom_keys, cgras)]
    pri_dct = {}
    for cgra, cpri_dct in zip(cgras, cpri_dcts):
        cpri_dct, cgra2 = _calculate_priorities_and_assign_stereo(
            cgra, par_eval_=par_eval_, par_eval2_=par_eval2_,
            break_ties=break_ties, backbone_only=backbone_only,
            pri_dct=cpri_dct)
        pri_dct.update(cpri_dct)
        gra2 = set_stereo_parities(gra2, stereo_parities(cgra2))

    return pri_dct, gra2


def _calculate_priorities_and_assign_stereo(
        gra, par_eval_=None, par_eval2_=None, break_ties=False,
        backbone_only=True, pri_dct=None):
    """ Determine canonical priorities and assign stereo parities to this graph

    This is how the parity evaluators are to be called:
    >>> par = par_eval_(pri_dct)(key)               # this returns the parity

    :param gra: a connected molecular graph
    :type gra: automol graph data structure
    :param par_eval_: A parity evaluator for assigning parities during the
        priority calculation.
    :param par_eval2_: An optional second parity evaluator for assigning
        the parities that will be returned, if different from those to be
        used for the priority calculation.
    :param break_ties: Break ties to determine canonical keys from
        canonical priorities?
    :type break_ties: bool
    :param backbone_only: Consider backbone atoms only?
    :type backbone_only: bool
    :param pri_dct: Optional initial priorities, to be refined.
    :type pri_dct: dict[int: int]
    :returns: A dictionary of canonical priorities by atom key and a graph
        with stereo assignments.
    :rtype: dict[int: int], molecular graph data structure
    """
    par_eval_ = (parity_evaluator_read_canonical_()
                 if par_eval_ is None else par_eval_)
    par_eval2_ = par_eval_ if par_eval2_ is None else par_eval2_

    # 1. Iteratively assign parities and refine priorities.
    def _algo(gra_, pri_dct_, ts_rev=False):
        # Perform a TS graph reversal, if requested
        # (Note that we *keep* stereo in `gra0`, if present, because it may
        # need to be read out by the parity evaluators.)
        gra0 = ts_reverse(gra_) if ts_rev else gra_

        # Graph 1 will be for the priority calculation, graph 2 for the parity
        # assignments that will be returned.
        gra1 = gra2 = without_stereo(gra0)

        pri_dct0 = 0
        pri_dct1 = pri_dct_
        while pri_dct0 != pri_dct1:
            # a. Store the current priorities for comparison.
            pri_dct0 = pri_dct1

            # b. Refine priorities based on the assignments in graph 1.
            pri_dct1 = refine_priorities(gra1, pri_dct1)

            # c. Find stereogenic atoms and bonds based on current priorities.
            keys = stereogenic_keys_from_priorities(gra1, pri_dct1)

            # d. If there are none, the calculation is complete. Exit the loop.
            if not keys:
                break

            # e. Assign parities to graph 1 using the first parity evaluator.
            p1_ = par_eval_(gra0, pri_dct1)
            gra1 = set_stereo_parities(gra1, {k: p1_(k) for k in keys})

            # f. Assign parities to graph 2 using the second parity evaluator.
            p2_ = par_eval2_(gra0, pri_dct1)
            gra2 = set_stereo_parities(gra2, {k: p2_(k) for k in keys})

        # If the graph was reversed, restore `gra2` to the original form
        gra2 = ts_reverse(gra2) if ts_rev else gra2
        return pri_dct1, gra1, gra2

    pri_dct, gra1, gra2 = _algo(gra, pri_dct)

    # 2. If this is a TS graph, rerun the algorithm on the reverse direction to
    # figure out which one is canonical
    if is_ts_graph(gra):
        rpri_dct, rgra1, rgra2 = _algo(gra, pri_dct, ts_rev=True)
        if not ts_is_canonical_direciton(gra1, pri_dct, rgra1, rpri_dct):
            pri_dct = rpri_dct
            gra1 = rgra1
            gra2 = rgra2

    # 3. If requested, break priority ties to determine canonical keys.
    if break_ties:
        pri_dct = break_priority_ties(gra1, pri_dct)

    # 4. If requested, add in priorities for explicit hydrogens.
    if not backbone_only:
        pri_dct = assign_hydrogen_priorities(
            gra, pri_dct, break_ties=break_ties)

    return pri_dct, gra2


def refine_priorities(gra, pri_dct=None):
    """ Refine the canonical priorities for this graph based on some sort value

    (Only for connected graphs)

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: A dictionary mapping atom keys to priorities
    :type pri_dct: dict
    :param srt_eval_: An evaluator for sort values, based on current
        priorities. Curried such that srt_val_(pri_dct)(key) returns the
        sort value.
    """
    assert is_connected(gra), "Not for disconnected graphs."
    assert gra == without_dummy_atoms(gra), (
        f"Remove dummy atoms:\n{gra}\n{without_dummy_atoms(gra)}")

    gra = implicit(gra)
    pri_dct = {} if pri_dct is None else pri_dct
    pri_dct = dict_.by_key(pri_dct, atom_keys(gra), fill_val=0)
    srt_eval_ = sort_evaluator_atom_invariants_(gra)

    ngb_keys_dct = atoms_neighbor_atom_keys(gra)

    cla_dct = class_dict_from_priority_dict(pri_dct)

    # Set up the new_clas list, containing priorities and priority classes that
    # are up for re-evaluation.
    new_cla_dct = dict_.filter_by_value(cla_dct, lambda v: len(v) > 1)
    new_clas = sorted(new_cla_dct.items(), reverse=True)

    while new_clas:
        # Pop the next priority class for re-evaluation
        idx, cla = new_clas.pop(0)

        # Sort and partition the priority class based on sort values. After the
        # first iteration, only the neighboring priority classes cause further
        # subdivision.
        srt_val_ = srt_eval_(pri_dct)
        cla = sorted(cla, key=srt_val_)
        parts = [tuple(ks) for _, ks in itertools.groupby(cla, srt_val_)]

        # Assign new priorities to the class partitions and update pri_dct and
        # cla_dct.
        new_idx = idx
        if len(parts) > 1:
            new_idxs = []
            for part in parts:
                cla_dct[new_idx] = part
                pri_dct.update({k: new_idx for k in part})

                # Track the set of new indices
                new_idxs.append(new_idx)

                # Increment the index for the next class by the number of
                # members in this one, so that that priorities are stable.
                new_idx += len(part)

            # Identify indices of classes with neighboring atoms, as these may
            # be affected by the re-classification.
            ngb_idxs = frozenset()
            for new_idx in new_idxs:
                new_cla = cla_dct[new_idx]

                # Get neighboring keys to the members of this new class.
                ngb_keys = frozenset.union(
                    *map(ngb_keys_dct.__getitem__, new_cla))

                # Get priorities of these neighboring atoms.
                ngb_idxs |= frozenset(map(pri_dct.__getitem__, ngb_keys))

                # Don't include classes that were already up for re-evaluation.
                ngb_idxs -= frozenset(dict(new_clas))

            for ngb_idx in sorted(ngb_idxs):
                ngb_cla = cla_dct[ngb_idx]
                if len(ngb_cla) > 1:
                    new_clas.insert(0, (ngb_idx, cla_dct[ngb_idx]))

    return pri_dct


def break_priority_ties(gra, pri_dct):
    """ Break ties within priority classes.

    (Only for connected graphs)

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: A dictionary mapping atom keys to priorities
    :type pri_dct: dict
    :param srt_eval_: An evaluator for sort values, based on current class
        indices. Curried such that srt_val_(pri_dct)(key) returns the sort
        value.
    """
    assert is_connected(gra), "Not for disconnected graphs."
    assert gra == without_dummy_atoms(gra), (
        f"Remove dummy atoms:\n{gra}\n{without_dummy_atoms(gra)}")

    pri_dct = pri_dct.copy()

    cla_dct = class_dict_from_priority_dict(pri_dct)

    # Set up the new_clas list, containing priorities and priority classes that
    # are up for re-evaluation.
    new_cla_dct = dict_.filter_by_value(cla_dct, lambda v: len(v) > 1)
    new_clas = sorted(new_cla_dct.items(), reverse=True)

    while new_clas:
        # Pop the next priority class for tie-breaking
        idx, cla = new_clas.pop(0)
        cla = list(cla)

        # Give the last element of this priority class a new index
        new_idx = idx + len(cla) - 1
        pri_dct[cla[-1]] = new_idx

        # Now, refine partitions based on the change just made.
        pri_dct = refine_priorities(gra, pri_dct)

        # Update the list of classes needing further tie breaking
        cla_dct = class_dict_from_priority_dict(pri_dct)
        new_cla_dct = dict_.filter_by_value(cla_dct, lambda v: len(v) > 1)
        new_clas = sorted(new_cla_dct.items(), reverse=True)

    return pri_dct


def sort_evaluator_atom_invariants_(gra):
    """ A sort function based on atom invariants with two levels of currying.

    To get the sort value for a specific key, use
        srt_val = sort_evaluator_atom_invariants_(gra)(pri_dct)(key)

    My reasoning for doing things this way is that `gra` never changes, but
    `pri_dct` does, so we need to be able to update the function with new
    index dictionaries. Ultimately, it is convenient to return a function
    of `key` only because this can be passed to standard python sorting and
    grouping functions such as `sorted()` and `itertools.groupby()`.

    The canonical order has been modified relative to the one used by
    Scheider (2015) to be more InChI-like (following Hill ordering).

    :param gra: molecular graph
    :type gra: automol graph data structure
    """
    def _replace_none(val):
        return numpy.inf if val is None else val

    def _replace_reacting_bond_order(val):
        """ Ensure that reacting bonds will sort after non-reacting bonds:
            non-reacting bonds < forming bonds < breaking bonds
        """
        assert val == round(val, 1)
        return int(val * 100) if val in (0.1, 0.9) else val

    def _normalize_symbol(symb):
        """ normalize atomic symbols to make them sort as follows:
            (C first, others in alphabetical order, H last)
            (Hydrogens should only appear for TS graphs)
        """
        symb = ptab.to_symbol(symb)
        if symb == 'C':
            symb = ''     # Sorts first (always)
        if symb == 'H':
            symb = 'zz'   # Sorts last against atomic symbols
        return symb

    # Normalize the graph before working with it
    gra = without_pi_bonds(implicit(gra))

    # For the main properties, remove reacting bonds before calculating
    gra_no_rxbs = without_bonds_by_orders(gra, [0.1, 0.9])
    bnds_dct_no_rxbs = atoms_bond_keys(gra_no_rxbs)

    symb_dct = dict_.transform_values(
        atom_symbols(gra_no_rxbs), _normalize_symbol)
    hnum_dct = atom_implicit_hydrogens(gra_no_rxbs)
    mnum_dct = mass_numbers(gra_no_rxbs)
    apar_dct = dict_.transform_values(
        atom_stereo_parities(gra_no_rxbs), _replace_none)

    bpar_dct = bond_stereo_parities(gra_no_rxbs)

    def _sortable_bond_stereo_values(bnd_keys):
        bpars = dict_.values_by_key(bpar_dct, bnd_keys)
        bpars = tuple(sorted(map(_replace_none, bpars)))
        return bpars

    bpars_dct = dict_.transform_values(
        bnds_dct_no_rxbs, _sortable_bond_stereo_values)

    # For bond orders, *KEEP* reacting bonds
    bord_dct = bond_orders(gra)

    def _sortable_bond_orders(bnd_keys):
        bords = dict_.values_by_key(bord_dct, bnd_keys)
        bords = tuple(sorted(map(_replace_reacting_bond_order, bords)))
        return bords

    bords_dct = dict_.transform_values(
        atoms_bond_keys(gra, ts_=True), _sortable_bond_orders)

    # For neighboring keys, *KEEP* reacting bonds
    nkeys_dct = atoms_neighbor_atom_keys(gra, ts_=True)

    def _evaluator(pri_dct):
        """ Sort value evaluator based on current priorities.

        :param pri_dct: A dictionary mapping atom keys to priorities
        :type pri_dct: dict
        """

        def _value(key):
            symb = symb_dct[key]        # symbol
            deg = len(bnds_dct_no_rxbs[key])    # number of bonds
            hnum = hnum_dct[key]        # number of hydrogens
            mnum = mnum_dct[key]
            apar = apar_dct[key]
            bpars = bpars_dct[key]
            bords = bords_dct[key]
            nidxs = tuple(sorted(map(pri_dct.__getitem__, nkeys_dct[key])))
            return (symb, deg, hnum, mnum, apar, bpars, bords, nidxs)

        return _value

    return _evaluator


# # parity evaluators
def parity_evaluator_from_geometry_(geo=None, geo_idx_dct=None):
    r""" Determines stereo parity from a geometry

    :param geo: molecular geometry
    :type geo: automol geometry data structure
    :param geo_idx_dct: If they don't already match, specify which graph
        keys correspond to which geometry indices.
    :type geo_idx_dct: dict[int: int]
    :returns: A parity evaluator, curried such that par_eval_(pri_dct)(key)
        returns the parity for a given atom, given a set of priorities.
    """
    geo_idx_dct_ = geo_idx_dct

    def _evaluator(gra, pri_dct):
        """ Parity evaluator based on current priorities.

        :param gra: molecular graph
        :type gra: automol graph data structure
        :param pri_dct: A dictionary mapping atom keys to priorities.
        :type pri_dct: dict
        """
        atm_keys = sorted(atom_keys(gra))
        geo_idx_dct = (geo_idx_dct_ if geo_idx_dct_ is not None
                       else {k: i for i, k in enumerate(sorted(atm_keys))})

        assert gra == explicit(gra), (
            "Explicit graph should be used when evaluating from geometry.")
        gra = without_dummy_atoms(gra)

        pri_dct = assign_hydrogen_priorities(
            gra, pri_dct, break_ties=False, neg=True)

        def _parity(key):
            # If the key is a number, this is an atom
            if isinstance(key, numbers.Number):
                nkeys = atom_stereo_sorted_neighbor_keys(
                    gra, key, pri_dct=pri_dct)

                # Get the atom parity
                par = geometry_atom_parity(
                    gra, geo, key, nkeys, geo_idx_dct=geo_idx_dct)

            # Otherwise, this is a bond
            else:
                assert isinstance(key, abc.Collection) and len(key) == 2, (
                    f"{key} is not a valid bond key.")
                key1, key2 = key
                nkey1s, nkey2s = bond_stereo_sorted_neighbor_keys(
                    gra, key1, key2, pri_dct=pri_dct)

                # Get the bond parity
                par = geometry_bond_parity(
                    gra, geo, (key1, key2), (nkey1s, nkey2s),
                    geo_idx_dct=geo_idx_dct)

            return par

        return _parity

    return _evaluator


def parity_evaluator_read_canonical_():
    """ Determines stereo parity from a graph with canonical stereo

    This is the trivial case, where parities in the graph are already
    assumed to be canonical and so nothing needs to be done to calculate
    them.

    :returns: A parity evaluator, curried such that par_eval_(pri_dct)(key)
        returns the parity for a given atom, given a set of priorities.
    """

    def _evaluator(gra, pri_dct):
        """ Parity evaluator based on current priorities

        Class indices are ignored, since the parities are assumed to be
        canonical.

        :param gra: molecular graph with canonical stereo parities
        :type gra: automol graph data structure
        :param pri_dct: A dictionary mapping atom keys to priorities
        :type pri_dct: dict
        """
        atm_par_dct = atom_stereo_parities(gra)
        bnd_par_dct = bond_stereo_parities(gra)

        # Do-nothing line to prevent linting complaint
        assert pri_dct or not pri_dct

        def _parity(key):
            # If the key is a number, this is an atom
            if isinstance(key, numbers.Number):
                par = atm_par_dct[key]
            # Otherwise, this is a bond
            else:
                assert isinstance(key, abc.Collection) and len(key) == 2, (
                    f"{key} is not a valid bond key.")
                par = bnd_par_dct[key]
            return par

        return _parity

    return _evaluator


def parity_evaluator_flip_local_():
    """ Determines canonical from local stereo parity or vice versa (same
    operation)

    Local parities are based directly on the key values of neighboring
    atoms, whereas canonical parities are based on their canonical
    priorities.  Consequently, local parities are specific to the
    particular way the graph is labeled, so the graph cannot be relabeled
    without corrupting stereo information, but they are useful for
    temporarily decoupling stereo parities from each other as the graph is
    manipulated in other ways.

    Note that, for consistency with InChI and other systems, hydrogen keys
    are treated as having lowest priority. This is done by setting their
    sort value to negative infinity.

    :returns: A parity evaluator, curried such that par_eval_(pri_dct)(key)
        returns the parity for a given atom, given a set of priorities.
    """

    def _evaluator(gra, pri_dct):
        """ Parity evaluator based on current priorities

            Class indices are ignored, since the parities are assumed to be
            local.

            :param gra: molecular graph with local stereo parities
            :type gra: automol graph data structure
            :param pri_dct: A dictionary mapping atom keys to priorities.
            :type pri_dct: dict
        """
        gra = explicit(gra)
        atm_par_dct = atom_stereo_parities(gra)
        bnd_par_dct = bond_stereo_parities(gra)

        loc_pri_dct = local_priority_dict(gra)

        pri_dct = assign_hydrogen_priorities(
            gra, pri_dct, break_ties=False, neg=True)

        def _parity(key):
            # If the key is a number, this is an atom
            if isinstance(key, numbers.Number):
                par = atm_par_dct[key]

                can_srt = atom_stereo_sorted_neighbor_keys(
                    gra, key, pri_dct=pri_dct)
                loc_srt = sorted(can_srt, key=loc_pri_dct.__getitem__)

                if util.is_even_permutation(loc_srt, can_srt):
                    ret_par = par
                else:
                    ret_par = not par
            # Otherwise, this is a bond
            else:
                assert isinstance(key, abc.Collection) and len(key) == 2, (
                    f"{key} is not a valid bond key.")
                par = bnd_par_dct[key]

                key1, key2 = key
                nkey1s, nkey2s = bond_stereo_sorted_neighbor_keys(
                    gra, key1, key2, pri_dct=pri_dct)

                can_nmax1 = nkey1s[-1]
                can_nmax2 = nkey2s[-1]
                loc_nmax1 = max(nkey1s, key=loc_pri_dct.__getitem__)
                loc_nmax2 = max(nkey2s, key=loc_pri_dct.__getitem__)

                if not (loc_nmax1 == can_nmax1) ^ (loc_nmax2 == can_nmax2):
                    ret_par = par
                else:
                    ret_par = not par

            return ret_par

        return _parity

    return _evaluator


# # core algorithm helpers
def stereogenic_keys_from_priorities(gra, pri_dct, assigned=False):
    """ Find stereogenic atoms and bonds in this graph, given a set of atom
    priority values

    If the `assigned` flag is set to `False`, only  unassigned stereogenic
    bonds will be detected.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :param assigned: Include bonds that already have stereo assignments?
    :param assigned: bool
    :returns: the stereogenic atom and bond keys
    :rtype: frozenset
    """
    ste_atm_keys = stereogenic_atom_keys_from_priorities(
        gra, pri_dct, assigned=assigned)
    ste_bnd_keys = stereogenic_bond_keys_from_priorities(
        gra, pri_dct, assigned=assigned)
    return ste_atm_keys | ste_bnd_keys


def stereogenic_atom_keys_from_priorities(gra, pri_dct, assigned=False):
    """ Find stereogenic atoms in this graph, given a set of atom priority
    values

    If the `assigned` flag is set to `False`, only  unassigned stereogenic
    atoms will be detected.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :param assigned: Include atoms that already have stereo assignments?
    :type assigned: bool
    :returns: the stereogenic atom keys
    :rtype: frozenset[int]
    """
    gra = without_pi_bonds(gra)
    gra = explicit(gra)  # for simplicity, add the explicit hydrogens back in
    pri_dct = assign_hydrogen_priorities(
        gra, pri_dct, break_ties=False)

    atm_keys = tetrahedral_atom_keys(gra)
    if not assigned:
        # Remove assigned stereo keys
        atm_keys -= atom_stereo_keys(gra)

    def _is_stereogenic(key):
        nkeys = atom_stereo_sorted_neighbor_keys(gra, key, pri_dct=pri_dct)
        assert len(nkeys) <= 4, f"Too many neighbors! {nkeys}"
        pris = list(map(pri_dct.__getitem__, nkeys))
        return len(set(pris)) == len(pris)

    ste_atm_keys = frozenset(filter(_is_stereogenic, atm_keys))
    return ste_atm_keys


def stereogenic_bond_keys_from_priorities(gra, pri_dct, assigned=False):
    """ Find stereogenic bonds in this graph, given a set of atom priority
    values

    If the `assigned` flag is set to `False`, only  unassigned stereogenic
    bonds will be detected.

    :param gra: molecular graph
    :type gra: automol graph data structure
    :param pri_dct: priorities, to avoid recalculating
    :type pri_dct: dict[int: int]
    :param assigned: Include bonds that already have stereo assignments?
    :param assigned: bool
    :returns: the stereogenic bond keys
    :rtype: frozenset[frozenset[int]]
    """
    gra = without_pi_bonds(gra)
    gra = explicit(gra)  # for simplicity, add the explicit hydrogens back in
    pri_dct = assign_hydrogen_priorities(
        gra, pri_dct, break_ties=False)

    bnd_keys = rigid_planar_bond_keys(gra)
    if not assigned:
        # Remove assigned stereo keys
        bnd_keys -= bond_stereo_keys(gra)

    # Don't treat as a TS graph when checking for small rings
    rng_bnd_keys_lst = rings_bond_keys(gra, ts_=False)
    bnd_keys -= functools.reduce(  # remove double bonds in small rings
        frozenset.union,
        filter(lambda x: len(x) < 8, rng_bnd_keys_lst), frozenset())

    def _is_stereogenic(key):
        key1, key2 = key
        nkey1s, nkey2s = bond_stereo_sorted_neighbor_keys(
            gra, key1, key2, pri_dct=pri_dct)

        ret = True
        for nkeys in (nkey1s, nkey2s):
            assert len(nkeys) <= 2, f"Too many neighbors! {nkeys}"
            pris = list(map(pri_dct.__getitem__, nkeys))
            ret &= (False if not nkeys else         # C=:O:
                    True if len(nkeys) == 1 else    # C=N:-X
                    len(set(pris)) == len(pris))    # C=C(-X)-Y

        return ret

    ste_bnd_keys = frozenset(filter(_is_stereogenic, bnd_keys))
    return ste_bnd_keys


def assign_hydrogen_priorities(gra, pri_dct, break_ties=False, neg=False):
    """ Assign priorities to hydrogens, negating them on request

    :param neg: Negate hydrogen keys, to give them lowest priority?
    :param neg: bool
    """
    pri_dct = pri_dct.copy()

    # Backbone hydrogens are always included, so only non-backbone hydrogens
    # need to be assigned
    hyd_keys_pool = nonbackbone_hydrogen_keys(gra)

    if hyd_keys_pool:
        bbn_keys = sorted(backbone_keys(gra), key=pri_dct.__getitem__)
        bbn_pri_dct = dict_.by_key(pri_dct, bbn_keys)
        gra = explicit(gra)

        hyd_keys_dct = atom_nonbackbone_hydrogen_keys(gra)

        next_idx = max(bbn_pri_dct.values()) + 1

        # If not breaking ties, assign equal priority to hydrogens bonded to
        # atoms from the same priority class.
        hyd_pri_dct = {}
        if not break_ties:
            # Partition hydrogens into classes based on their parent atoms.
            bbn_parts = sorted_classes_from_priority_dict(pri_dct)
            get_hyd_key_ = hyd_keys_dct.__getitem__
            hyd_parts = [
                list(itertools.chain(*map(get_hyd_key_, bbn_part)))
                for bbn_part in bbn_parts]
            for hyd_part in hyd_parts:
                hyd_pri_dct.update({k: next_idx for k in hyd_part})
                next_idx += len(hyd_part)
        # Otherwise, give each hydrogen a unique label.
        else:
            srt_hyd_keys = itertools.chain(
                *map(hyd_keys_dct.__getitem__, bbn_keys))
            hyd_pri_dct.update({k: (i+next_idx) for i, k in
                                enumerate(srt_hyd_keys)})

        hyd_pri_dct = dict_.by_key(hyd_pri_dct, hyd_keys_pool)
        pri_dct.update(hyd_pri_dct)

    # If requested, negate priorities for *all* hydrogen keys, for consistency
    if neg:
        all_hyd_keys = atom_keys(gra, symb='H')
        pri_dct = {k: -abs(p) if k in all_hyd_keys else p
                   for k, p in pri_dct.items()}

    return pri_dct


def local_priority_dict(gra):
    """ Generate a local ``priority'' dictionary
    """
    loc_pri_dct = {}
    loc_pri_dct.update(
        {k: k for k in backbone_keys(gra, hyd=False)})
    loc_pri_dct.update(
        {k: -abs(k) for k in backbone_hydrogen_keys(gra)})
    loc_pri_dct.update(
        {k: -numpy.inf for k in nonbackbone_hydrogen_keys(gra)})
    return loc_pri_dct


def class_dict_from_priority_dict(pri_dct):
    """ Obtain a class dictionary from a priority dictionary.

    :param pri_dct: A dictionary mapping atom keys to priorities.
    :type pri_dct: dict
    :returns: A dictionary mapping priorities onto the full set of keys
        for that priority class, as a sorted tuple.
    :rtype: dict[int: tuple]
    """
    keys = sorted(pri_dct.keys())
    clas = sorted(keys, key=pri_dct.__getitem__)
    cla_dct = {i: tuple(c)
               for i, c in itertools.groupby(clas, key=pri_dct.__getitem__)}
    return cla_dct


def sorted_classes_from_priority_dict(pri_dct):
    """ Obtain classes from index dict, sorted by priority.

    :param pri_dct: A dictionary mapping atom keys to priorities.
    :type pri_dct: dict
    :returns: A tuple of tuples of keys for each priority class, sorted by
        priority value.
    :rtype: tuple[tuple[int]]
    """
    keys = sorted(pri_dct.keys())
    clas = sorted(keys, key=pri_dct.__getitem__)
    cla_dct = tuple(
        tuple(c) for _, c in itertools.groupby(clas, key=pri_dct.__getitem__))
    return cla_dct
