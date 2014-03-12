from django.contrib.contenttypes.models import ContentType
from django.contrib import messages
from django.utils.translation import ugettext as _
from django.contrib.admin.models import LogEntry, CHANGE
from django.utils.encoding import force_text, force_unicode
from django.contrib.admin.templatetags.admin_urls import add_preserved_filters
from django.http import HttpResponseRedirect


class FSMTransitionMixin(object):
    '''
    Mixin to use with `admin.ModelAdmin` to support transitioning
    a model from one state to another (workflow style).

    * The change_form.html must be overriden to use the custom submit
      row template (on a model or global level).

          {% load fsm_workflow %}
          {% block submit_buttons_bottom %}{% fsm_submit_row %}{% endblock %}

    * There must be one and only one FSMField on the model.
    * There must be a corresponding model function to run the transition,
      generally decorated with the transition decorator. This is what
      determines the available transitions. Without a function, the action
      in the submit row will not be available.
    * In the absence of specific transition permissions, the user must
      have change permission for the model.
    '''

    # name of the FSMField on the model to transition
    fsm_field = 'state'

    def _fsm_get_transitions(self, obj, perms=None):
        '''
        Gets a list of transitions available to the user.

        Available state transitions are provided by django-fsm
        following the pattern get_available_FIELD_transitions
        '''
        transitions_func = 'get_available_{}_transitions'.format(self.fsm_field)
        transitions = getattr(obj, transitions_func)() if obj else []
        return transitions

    def get_redirect_url(self, request, obj):
        """
        Hook to adjust the redirect post-save.
        """
        return request.path

    def response_change(self, request, obj):
        '''
        Override of `ModelAdmin.response_change` to detect the FSM button
        that was clicked in the submit row and perform the state transtion.
        '''
        # Each transition button is named with the transition.
        # e.g. _fsmtransition-publish
        #      _fsmtransition-delete
        transition_key = [k for k in request.POST.keys() if k.startswith("_fsmtransition")]
        if not transition_key:
            return super(FSMTransitionMixin, self).response_change(request, obj)

        # Extract the function name from the transition key
        transition = transition_key[0].split('-')[1]
        original_state = getattr(obj, self.fsm_field)
        msg_dict = {
            'obj': force_text(obj),
            'transition': transition,
        }

        # Ensure the requested transition is availble
        transitions = self._fsm_get_transitions(obj)
        available = any([func.func_name == transition for target, func in transitions])
        trans_func = getattr(obj, transition, None)

        if available and trans_func:
            # Run the transition
            trans_func()

            # The transition may not be marked to automatically save, so
            # we assume that it should always be saved.
            obj.save()
            new_state = obj.state

            # Done! Log the change and message user
            self.log_state_change(obj, request.user.id, original_state, new_state)
            msg_dict.update({'new_state': new_state})
            msg = _('%(obj)s successfully set to %(new_state)s') % msg_dict
            self.message_user(request, msg, messages.SUCCESS)
        else:
            msg = _('Error! %(obj)s failed to %(transition)s') % msg_dict
            self.message_user(request, msg, messages.ERROR)

        opts = self.model._meta
        redirect_url = self.get_redirect_url(request=request, obj=obj)

        preserved_filters = self.get_preserved_filters(request)
        redirect_url = add_preserved_filters({'preserved_filters': preserved_filters, 'opts': opts}, redirect_url)
        return HttpResponseRedirect(redirect_url)

    def log_state_change(self, obj, user_id, original_state, new_state):
        '''
        Log the transition of the object to the history.
        '''
        LogEntry.objects.log_action(
            user_id=user_id,
            content_type_id=ContentType.objects.get_for_model(obj.__class__).pk,
            object_id=obj.pk,
            object_repr=force_unicode(obj),
            action_flag=CHANGE,
            change_message='Changed state from {0} to {1}'.format(original_state, new_state),
        )