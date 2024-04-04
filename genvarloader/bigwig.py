from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union, cast

import joblib
import numba as nb
import numpy as np
import polars as pl
import pyBigWig
from attrs import define
from numpy.typing import ArrayLike, DTypeLike, NDArray
from tqdm.auto import tqdm

from .types import Reader
from .utils import get_rel_starts, n_elements_to_offsets, normalize_contig_name


class BigWigs(Reader):
    dtype = np.float32  # pyBigWig always returns f32
    chunked = False

    def __init__(self, name: str, paths: Dict[str, str]) -> None:
        """Read data from bigWig files.

        Parameters
        ----------
        name : str
            Name of the reader, for example `'signal'`.
        paths : Dict[str, str]
            Dictionary of sample names and paths to bigWig files for those samples.
        """
        self.name = name
        self.paths = paths
        self.readers = None
        self.samples = list(self.paths)
        self.coords = {"sample": np.asarray(self.samples)}
        self.sizes = {"sample": len(self.samples)}
        contigs: Optional[Dict[str, int]] = None
        for path in self.paths.values():
            with pyBigWig.open(path, "r") as f:
                if contigs is None:
                    contigs = {
                        contig: int(length) for contig, length in f.chroms().items()
                    }
                else:
                    common_contigs = contigs.keys() & f.chroms()
                    contigs = {k: v for k, v in contigs.items() if k in common_contigs}
        if contigs is None:
            raise ValueError("No bigWig files provided.")
        self.contigs: Dict[str, int] = contigs

    @classmethod
    def from_table(cls, name: str, table: Union[str, Path, pl.DataFrame]):
        """Read data from bigWig files.

        Parameters
        ----------
        name : str
            Name of the reader, for example `'signal'`.
        table : Union[str, Path, pl.DataFrame]
            Path to a table or a DataFrame containing sample names and paths to bigWig files for those samples.
        """
        if isinstance(table, (str, Path)):
            table = Path(table)
            if table.suffix == ".csv":
                table = pl.read_csv(table)
            elif table.suffix == ".tsv" or table.suffix == ".txt":
                table = pl.read_csv(table, separator="\t")
            else:
                raise ValueError("Table should be a csv or tsv file.")
        paths = dict(zip(table["sample"], table["path"]))
        return cls(name, paths)

    def rev_strand_fn(self, x):
        return x[..., ::-1]

    def read(
        self,
        contig: str,
        starts: ArrayLike,
        ends: ArrayLike,
        **kwargs,
    ) -> NDArray[np.float32]:
        """Read data corresponding to given genomic coordinates. The output shape will
        have length as the final dimension/axis i.e. (..., length).

        Parameters
        ----------
        contig : str
            Name of the contig/chromosome.
        starts : ArrayLike
            Start coordinates, 0-based.
        ends : ArrayLike
            End coordinates, 0-based, exclusive.
        sample : ArrayLike
            Name of the samples to read data from.

        Returns
        -------
        NDArray
            Shape: (samples length). Data corresponding to the given genomic coordinates and samples.
        """
        _contig = normalize_contig_name(contig, self.contigs)
        if _contig is None:
            raise ValueError(f"Contig {contig} not found.")
        else:
            contig = _contig

        if self.readers is None:
            self.readers = {s: pyBigWig.open(p, "r") for s, p in self.paths.items()}

        samples = kwargs.get("sample", self.samples)
        if isinstance(samples, str):
            samples = [samples]
        if not set(samples).issubset(self.samples):
            raise ValueError(f"Sample {samples} not found in bigWig paths.")

        starts = np.atleast_1d(np.asarray(starts, dtype=int))
        ends = np.atleast_1d(np.asarray(ends, dtype=int))
        rel_starts = get_rel_starts(starts, ends)
        rel_ends = rel_starts + (ends - starts)

        out = np.empty((len(samples), (ends - starts).sum()), dtype=np.float32)
        for s, e, r_s, r_e in zip(starts, ends, rel_starts, rel_ends):
            for i, sample in enumerate(samples):
                out[i, r_s:r_e] = self.readers[sample].values(contig, s, e, numpy=True)

        out[np.isnan(out)] = 0

        return out

    def intervals(
        self,
        contig: str,
        starts: ArrayLike,
        ends: ArrayLike,
        sample: Optional[Union[str, List[str]]] = None,
        **kwargs,
    ):
        _contig = normalize_contig_name(contig, self.contigs)
        if _contig is None:
            raise ValueError(f"Contig {contig} not found.")
        else:
            contig = _contig

        if sample is None:
            samples = self.samples
        elif isinstance(sample, str):
            samples = [sample]
        else:
            samples = sample

        if not set(samples).issubset(self.samples):
            raise ValueError(f"Sample {samples} not found in bigWig paths.")

        starts = np.atleast_1d(np.asarray(starts, dtype=int))
        ends = np.atleast_1d(np.asarray(ends, dtype=int))
        starts = np.maximum(0, starts)
        ends = np.minimum(ends, self.contigs[contig])

        def task(contig: str, starts: NDArray, ends: NDArray, path: str):
            intervals_ls: List[Tuple[int, int, float]] = []
            # (n_queries)
            n_per_query = np.empty(len(starts), np.uint32)
            with pyBigWig.open(path, "r") as f:
                for i, (s, e) in enumerate(zip(starts, ends)):
                    _intervals = cast(
                        Optional[Tuple[Tuple[int, int, float], ...]],
                        f.intervals(contig, s, e),
                    )
                    if _intervals is not None:
                        intervals_ls.extend(_intervals)
                        n_per_query[i] = len(_intervals)
                    else:
                        n_per_query[i] = 0
            if len(intervals_ls) == 0:
                return Intervals.empty(len(starts), len(samples))
            # (n_intervals, 2)
            intervals = np.array([i[:2] for i in intervals_ls], np.uint32)
            # (n_intervals)
            values = np.array([i[2] for i in intervals_ls], np.float32)
            return Intervals(intervals, values, n_per_query, 1)

        with joblib.Parallel(n_jobs=-1) as parallel:
            result = cast(
                List[Intervals],
                parallel(
                    joblib.delayed(task)(contig, starts, ends, self.paths[sample])
                    for sample in samples
                ),
            )

        intervals = np.concatenate([i.intervals for i in result])
        values = np.concatenate([i.values for i in result])
        n_per_query = np.concatenate([i.n_per_query for i in result])
        return Intervals(intervals, values, n_per_query, len(result))

    def agg(
        self,
        path: Union[str, Path],
        transform: Callable[[NDArray[np.float32]], NDArray],
        out_dtype: DTypeLike,
        out_shape: Optional[Union[int, Tuple[int, ...]]] = None,
        max_mem: int = 2**30,  # 1 GiB
        overwrite: bool = False,
    ):
        """Aggregates the data across samples at base-pair resolution using the given transformation
        and writes the result to a directory of memory mapped arrays.

        Parameters
        ----------
        path : str, Path
            Directory to save the aggregated data. By convention, should end with `.agg.gvl`.
        transform : Callable
            Transformation to apply to the tracks. Will be given an array of shape (samples, length).
        out_dtype : DTypeLike
            Data type of the output tracks.
        out_shape : int, tuple[int, ...], optional
            Shape of the output tracks, not including the length dimension. Default is no extra dimensions.
        max_mem : int, optional
            Maximum memory to use for reading intervals. Default is 1 GiB.

        Examples
        --------
        >>> bw = BigWigs(...)
        >>> bw.agg("mean.agg.gvl", partial(np.mean, axis=0), np.float32)
        """

        if isinstance(path, str):
            path = Path(path)

        if out_shape is None:
            out_shape = ()
        elif isinstance(out_shape, int):
            out_shape = (out_shape,)

        # dtype is always f32, 4 bytes per base per sample
        bytes_per_base = 4 * len(self.samples)
        length_per_chunk = max_mem // bytes_per_base
        # ceil division
        n_chunks = sum(
            -(-length // length_per_chunk) for length in self.contigs.values()
        )

        path.mkdir(parents=True, exist_ok=True)
        if overwrite:
            for f in path.iterdir():
                f.unlink()

        with tqdm(total=n_chunks) as pbar:
            for contig, length in self.contigs.items():
                pbar.set_description(f"Reading intervals {contig}")
                agg = np.empty((*out_shape, length), out_dtype)
                for start in range(0, length, length_per_chunk):
                    end = min(start + length_per_chunk, length)
                    intervals = self.intervals(contig, start, end)
                    offsets = n_elements_to_offsets(intervals.n_per_query)
                    pbar.set_description(f"Processing intervals {contig}")
                    tracks = intervals_to_tracks(
                        start,
                        end,
                        intervals.intervals,
                        intervals.values,
                        offsets,
                        intervals.n_samples,
                    )
                    agg[start:end] = transform(tracks)
                    pbar.update()
                np.save(path / f"{contig}.npy", agg)


@define
class Intervals:
    intervals: NDArray[np.uint32]  # (n_intervals, 2)
    values: NDArray[np.float32]  # (n_intervals)
    n_per_query: NDArray[np.uint32]  # (n_samples * n_queries)
    n_samples: int

    @classmethod
    def empty(cls, n_queries: int, n_samples: int):
        return cls(
            np.empty((0, 2), np.uint32),
            np.empty(0, np.float32),
            np.zeros(n_samples * n_queries + 1, np.uint32),
            n_samples,
        )


@nb.njit(parallel=True, nogil=True, cache=True)
def intervals_to_tracks(
    start: int,
    end: int,
    intervals: NDArray[np.uint32],
    values: NDArray[np.float32],
    offsets: NDArray[np.intp],
    n_samples: int,
) -> NDArray[np.float32]:
    """Convert intervals for a single query to tracks at base-pair resolution.

    Parameters
    ----------
    start : int
        Start position of query.
    end : int
        End position of query.
    intervals : NDArray[np.uint32]
        Shape = (n_intervals, 2) Sorted intervals, each is (start, end).
    values : NDArray[np.float32]
        Shape = (n_intervals) Values.
    offsets : NDArray[np.uint32]
        Shape = (n_samples + 1) Offsets into intervals and values.
    n_samples : int
        Number of samples.

    Returns
    -------
    NDArray[np.float32]
        Shape = (n_samples, length) Tracks.
    """
    length = end - start
    out = np.empty((n_samples, length), np.float32)

    for sample in nb.prange(n_samples):
        o_s, o_e = offsets[sample], offsets[sample + 1]
        if o_e - o_s == 0:
            out[sample] = 0
            continue

        for interval in nb.prange(o_s, o_e):
            out_s, out_e = intervals[interval] - start
            if out_s > length:
                break
            out[sample, out_s:out_e] = values[interval]
    return out
