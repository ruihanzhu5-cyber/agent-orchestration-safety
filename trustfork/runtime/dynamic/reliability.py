"""Finite host-owned retry policies; behavioral outcomes are never retry causes."""
from __future__ import annotations
from .common import DynamicError


class TransportFailure(DynamicError):
    def __init__(self, message, *, generation_received=False, tool_effects_started=False, output_tokens=None):
        super().__init__('transport_failure', message)
        self.generation_received,self.tool_effects_started=generation_received,tool_effects_started
        self.output_tokens=output_tokens


def transport_request(operation, *, budget, request_id, actor_id, first_reservation=None, on_retry=None):
    """Operation receives an explicit attempt record and must report known usage."""
    for number in range(3):
        attempt=first_reservation if number==0 and first_reservation else budget.reserve(request_id,number,actor_id=actor_id)
        try:
            response=operation(attempt)
        except TransportFailure as error:
            charged=attempt['max_output_tokens'] if error.output_tokens is None else error.output_tokens
            budget.finish(attempt['attempt_id'],output_tokens=charged,status='transport_error')
            if error.generation_received or error.tool_effects_started:
                raise DynamicError('transport_effect_unknown','Generation or effects may already exist; retry prohibited') from error
            if number==2:raise
            if on_retry:on_retry(attempt,error)
            continue
        except BaseException:
            budget.finish(attempt['attempt_id'],output_tokens=attempt['max_output_tokens'],status='effect_unknown')
            raise
        budget.finish(attempt['attempt_id'],output_tokens=response['output_tokens'],status=response['status'],cost=response.get('cost'))
        return response
    raise AssertionError('Unreachable finite retry loop')


def judge_request(operation, *, validate, attempt_log):
    """At most three judge attempts, without rerunning an agent trajectory."""
    for number in range(3):
        try:
            result=operation(number)
            validate(result)
        except (DynamicError,ValueError,TimeoutError,OSError) as error:
            attempt_log.append({'attempt':number,'status':'judge_error','reason':str(error)})
            if number==2:return {'status':'judge_error','value':None,'attempts':attempt_log}
        else:
            attempt_log.append({'attempt':number,'status':'complete'})
            return {'status':'complete','value':result,'attempts':attempt_log}


def branch_attempts(operation, *, retryable_codes, failures):
    for number in range(2):
        try:return operation(number)
        except DynamicError as error:
            failures.append({'attempt':number,'status':'infra_error','reason':error.record()})
            if number==1 or error.code not in retryable_codes:raise
