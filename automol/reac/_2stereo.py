""" stereo functionality for reaction objects
"""
import copy
import yaml
import automol.graph
import automol.geom
import automol.chi
from automol.reac._0core import Reaction
from automol.reac._0core import from_forward_reverse


def expand_stereo(rxn: Reaction, enant=True):
    """ Expand all possible stereo assignments for the reactants and products
    of this reaction. Only includes possibilities that are mutually consistent
    with each other.

        :param rxn: a reaction object
        :type rxn: Reaction
        :param enant: Include all enantiomers? Otherwise, includes only
            canonical enantiomer species and reactions.
        :type enant: bool
        :returns: a sequence reaction objects with stereo assignments
        :rtype: Reaction
    """
    tsg = automol.graph.without_stereo(rxn.ts_graph)
    tsg0 = automol.graph.without_dummy_atoms(tsg)

    srxns = []
    for stsg0 in automol.graph.expand_stereo(tsg0, enant=enant):
        srxn = copy.deepcopy(rxn)

        # To keep both sets of dummy atoms, copy the stereo parities over
        srxn.ts_graph = automol.graph.set_stereo_parities(
            tsg, automol.graph.stereo_parities(stsg0))
        srxns.append(srxn)

    srxns = tuple(srxns)
    return srxns


def expand_stereo_for_reaction(rxn: Reaction, rcts_gra, prds_gra):
    """ Expand stereo to be consistent with the reactants and products

    :param rxn: _description_
    :type rxn: _type_
    :param rcts_gra: _description_
    :type rcts_gra: _type_
    :param prds_gra: _description_
    :type prds_gra: _type_
    """
    # Steps:
    # 1. Align products with reactants
    # 2. Expand all TSs
    # 3.


def from_old_string(rxn_str, one_indexed=True):
    """ Write a reaction object to a string

        :param rxn_str: string containing the reaction object
        :type rxn_str: str
        :param one_indexed: parameter to store keys in one-indexing
        :type one_indexed: bool
        :rtype: Reaction
    """
    yaml_dct = yaml.load(rxn_str, Loader=yaml.FullLoader)

    cla = yaml_dct['reaction class']
    rcts_keys = yaml_dct['reactants keys']
    prds_keys = yaml_dct['products keys']

    if one_indexed:
        rcts_keys = [[k-1 for k in ks] for ks in rcts_keys]
        prds_keys = [[k-1 for k in ks] for ks in prds_keys]

    ftsg_dct = {
        'atoms': yaml_dct['forward TS atoms'],
        'bonds': yaml_dct['forward TS bonds']}
    ftsg0 = automol.graph.from_yaml_dictionary(ftsg_dct,
                                               one_indexed=one_indexed)
    # rcts_gra = automol.graph.ts.reactants_graph(ftsg0)

    rtsg_dct = {
        'atoms': yaml_dct['backward TS atoms'],
        'bonds': yaml_dct['backward TS bonds']}
    rtsg0 = automol.graph.from_yaml_dictionary(rtsg_dct,
                                               one_indexed=one_indexed)
    # prds_gra = automol.graph.ts.reactants_graph(rtsg0)

    ftsg = automol.graph.without_stereo(ftsg0)
    rtsg = automol.graph.without_stereo(rtsg0)
    rxn = from_forward_reverse(cla, ftsg, rtsg, rcts_keys, prds_keys)

    # Now, work out the combined stereochemistry
    # rxn = expand_stereo_for_reaction(rxn, rcts_gra, prds_gra)[0]

    return rxn


def reflect(srxn: Reaction):
    """ Reflect all graphs in this reaction, to obtain their mirror images

        :param srxn: a reaction object with stereo assignments
        :type srxn: Reaction
        :returns: a reflected reaction object
    """
    srxn = copy.deepcopy(srxn)
    srxn.ts_graph = automol.graph.reflect(srxn.ts_graph)
    return srxn
