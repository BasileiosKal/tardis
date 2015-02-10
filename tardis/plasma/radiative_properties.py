import logging

import numpy as np
import pandas as pd

from astropy import units as u, constants as const

from tardis.plasma.base_properties import ProcessingPlasmaProperty

logger = logging.getLogger(__name__)


class TauSobolev(ProcessingPlasmaProperty):
    """
    This function calculates the Sobolev optical depth :math:`\\tau_\\textrm{Sobolev}`

    .. math::
        C_\\textrm{Sobolev} = \\frac{\\pi e^2}{m_e c}

        \\tau_\\textrm{Sobolev} = C_\\textrm{Sobolev}\,  \\lambda\\, f_{\\textrm{lower}\\rightarrow\\textrm{upper}}\\,
            t_\\textrm{explosion}\, N_\\textrm{lower}



    .. note::
        Currently we're ignoring the term for stimulated emission:
            :math:`(1 - \\frac{g_\\textrm{lower}}{g_\\textrm{upper}}\\frac{N_\\textrm{upper}}{N_\\textrm{lower}})`


    """

    name = 'tau_sobolev'


    def __init__(self, plasma_parent):
        super(TauSobolev, self).__init__(plasma_parent)
        self.sobolev_coefficient = (((np.pi * const.e.gauss ** 2) /
                                    (const.m_e.cgs * const.c.cgs))
                                    * u.cm * u.s / u.cm**3).to(1).value
        self._g_upper = None
        self._g_lower = None



    def get_g_lower(self, levels, lines_lower_level_index):
        if self._g_lower is None:
            g_lower = np.array(levels.g.iloc[lines_lower_level_index],
                                     dtype=np.float64)
            self._g_lower = g_lower[np.newaxis].T
        return self._g_lower


    def get_g_upper(self, levels, lines_upper_level_index):
        if self._g_upper is None:
            g_upper = np.array(levels.g.iloc[lines_upper_level_index],
                                     dtype=np.float64)
            self._g_upper = g_upper[np.newaxis].T
        return self._g_upper



    def _calculate_stimulated_emission_factor(self, levels, n_lower, n_upper,
                                              lines_lower_level_index,
                                              lines_upper_level_index):
        """
        Calculating stimulated emission factor

        Parameters

        levels: ~pd.DataFrame
            with level information

        n_lower: ~np.ndarray
        :return:
        """

        meta_stable_upper = levels.metastable.values.take(
            lines_upper_level_index, axis=0, mode='raise')[np.newaxis].T

        g_lower = self.get_g_lower(levels, lines_lower_level_index)
        g_upper = self.get_g_upper(levels, lines_upper_level_index)

        stimulated_emission_factor = 1 - ((g_lower * n_upper) / (g_upper * n_lower))

        # getting rid of the obvious culprits
        stimulated_emission_factor[n_lower == 0.0] = 0.0
        stimulated_emission_factor[np.isneginf(stimulated_emission_factor)] = 0.0
        stimulated_emission_factor[meta_stable_upper &
                                   (stimulated_emission_factor < 0)] = 0.0

        return stimulated_emission_factor



    def calculate(self, lines, levels, level_number_density,
                  lines_upper_level_index, lines_lower_level_index,
                  time_explosion):

        f_lu = lines.f_lu.values[np.newaxis].T
        wavelength = lines.wavelength_cm.values[np.newaxis].T

        ### Why copy ??? #####
        n_lower = level_number_density.values.take(lines_lower_level_index, axis=0, mode='raise')
        n_upper = level_number_density.values.take(lines_upper_level_index, axis=0, mode='raise')

        stimulated_emission_factor = self._calculate_stimulated_emission_factor(
            levels, n_lower, n_upper, lines_lower_level_index,
            lines_upper_level_index)


        #if self.nlte_config is not None and self.nlte_config.species != []:
        #    nlte_lines_mask = np.zeros(self.stimulated_emission_factor.shape[0]).astype(bool)
        #    for species in self.nlte_config.species:
        #        nlte_lines_mask |= (self.atom_data.lines.atomic_number == species[0]) & \
        #                           (self.atom_data.lines.ion_number == species[1])
        #    self.stimulated_emission_factor[(self.stimulated_emission_factor < 0) & nlte_lines_mask[np.newaxis].T] = 0.0


        tau_sobolevs = (self.sobolev_coefficient * f_lu * wavelength *
                        time_explosion * n_lower * stimulated_emission_factor)

        return pd.DataFrame(tau_sobolevs, index=lines.index,
                            columns=np.array(level_number_density.columns))

class TransitionProbabilities(ProcessingPlasmaProperty):

    @staticmethod
    def calculate(macro_atom_data):
        """
            Updating the Macro Atom computations
        """

        if not hasattr(self, 'beta_sobolevs'):
            self.beta_sobolevs = np.zeros_like(self.tau_sobolevs.values)

        if not self.beta_sobolevs_precalculated:
            macro_atom.calculate_beta_sobolev(self.tau_sobolevs.values.ravel(order='F'),
                                          self.beta_sobolevs.ravel(order='F'))

        transition_probabilities = (macro_atom_data.transition_probability.values[np.newaxis].T *
                                    self.beta_sobolevs.take(self.atom_data.macro_atom_data.lines_idx.values.astype(int),
                                                            axis=0, mode='raise')).copy('F')
        transition_up_filter = (macro_atom_data.transition_type == 1).values
        macro_atom_transition_up_filter = macro_atom_data.lines_idx.values[transition_up_filter]
        j_blues = self.j_blues.values.take(macro_atom_transition_up_filter, axis=0, mode='raise')
        macro_stimulated_emission = self.stimulated_emission_factor.take(macro_atom_transition_up_filter, axis=0, mode='raise')
        transition_probabilities[transition_up_filter] *= j_blues * macro_stimulated_emission
        #Normalizing the probabilities
        block_references = np.hstack((self.atom_data.macro_atom_references.block_references,
                                      len(macro_atom_data)))
        macro_atom.normalize_transition_probabilities(transition_probabilities, block_references)
        return pd.DataFrame(transition_probabilities, index=macro_atom_data.transition_line_id,
                     columns=self.tau_sobolevs.columns)